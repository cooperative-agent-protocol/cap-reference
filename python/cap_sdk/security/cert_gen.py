# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""mTLS certificate generation for CAP deployments.

Generates a site CA, server certificate, and per-machine client certificates.
Client certificate CN is set to machine_id per Ch09 §9.2.1.

Usage:
    from cap_sdk.security.cert_gen import generate_site_ca, generate_server_cert, generate_machine_cert

    ca_cert, ca_key = generate_site_ca("my-site")
    srv_cert, srv_key = generate_server_cert(ca_cert, ca_key, "site-agent-01")
    cli_cert, cli_key = generate_machine_cert(ca_cert, ca_key, "excavator-01")
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Tuple

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _generate_key() -> ec.EllipticCurvePrivateKey:
    """Generate a P-256 EC private key."""
    return ec.generate_private_key(ec.SECP256R1())


def generate_site_ca(
    site_id: str,
    validity_days: int = 365,
) -> Tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Generate a self-signed site CA certificate.

    Args:
        site_id: Site identifier used in the CA subject CN.
        validity_days: Certificate validity in days.

    Returns:
        (ca_cert, ca_key) tuple.
    """
    key = _generate_key()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"CAP Site CA - {site_id}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CAP"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return cert, key


def generate_server_cert(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    server_id: str,
    hostnames: list[str] | None = None,
    validity_days: int = 365,
) -> Tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Generate a server certificate signed by the site CA.

    Args:
        ca_cert: The CA certificate.
        ca_key: The CA private key.
        server_id: Server/site-agent identifier used as CN.
        hostnames: SANs (DNS names). Defaults to ["localhost"].
        validity_days: Certificate validity in days.

    Returns:
        (server_cert, server_key) tuple.
    """
    if hostnames is None:
        hostnames = ["localhost"]

    key = _generate_key()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, server_id),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CAP"),
    ])

    san_names: list[x509.GeneralName] = [x509.DNSName(h) for h in hostnames]

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def generate_machine_cert(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    machine_id: str,
    validity_days: int = 365,
) -> Tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Generate a client certificate for a machine agent.

    The CN is set to machine_id per Ch09 §9.2.1. The Site Agent MUST verify
    that CapabilityManifest.machine_id matches the client cert CN.

    Args:
        ca_cert: The CA certificate.
        ca_key: The CA private key.
        machine_id: Machine identifier, used as CN.
        validity_days: Certificate validity in days.

    Returns:
        (machine_cert, machine_key) tuple.
    """
    key = _generate_key()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, machine_id),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CAP"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def write_pem(
    cert: x509.Certificate,
    key: ec.EllipticCurvePrivateKey,
    cert_path: str | Path,
    key_path: str | Path,
) -> None:
    """Write certificate and key to PEM files."""
    cert_path = Path(cert_path)
    key_path = Path(key_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def generate_site_certs(
    site_id: str,
    machine_ids: list[str],
    output_dir: str | Path = "certs",
) -> Path:
    """Generate a complete certificate set for a CAP site.

    Creates:
        {output_dir}/ca.pem, ca-key.pem
        {output_dir}/server.pem, server-key.pem
        {output_dir}/{machine_id}.pem, {machine_id}-key.pem  (for each machine)

    Args:
        site_id: Site identifier.
        machine_ids: List of machine identifiers.
        output_dir: Directory for output files.

    Returns:
        Path to the output directory.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ca_cert, ca_key = generate_site_ca(site_id)
    write_pem(ca_cert, ca_key, out / "ca.pem", out / "ca-key.pem")

    srv_cert, srv_key = generate_server_cert(ca_cert, ca_key, f"site-agent-{site_id}")
    write_pem(srv_cert, srv_key, out / "server.pem", out / "server-key.pem")

    for mid in machine_ids:
        m_cert, m_key = generate_machine_cert(ca_cert, ca_key, mid)
        write_pem(m_cert, m_key, out / f"{mid}.pem", out / f"{mid}-key.pem")

    return out
