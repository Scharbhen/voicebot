"""Сертификат для HTTPS (браузер даёт микрофон только по HTTPS).

  python make_cert.py OUT_DIR --names gpuwinsrv01.domain.corp,192.168.130.176
      → самоподписанный сертификат на 2 года (браузер один раз покажет предупреждение)
  python make_cert.py OUT_DIR --pfx corp.pfx --pfx-password ...
      → сертификат из корпоративного центра сертификации (без предупреждений)
Результат: OUT_DIR/cert.pem и OUT_DIR/key.pem
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


def write(out: Path, key, cert, chain=()) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    pem = cert.public_bytes(serialization.Encoding.PEM) + b"".join(
        c.public_bytes(serialization.Encoding.PEM) for c in chain)
    (out / "cert.pem").write_bytes(pem)


def self_signed(out: Path, names: list[str]) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sans = []
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=730))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    write(out, key, cert)


def from_pfx(out: Path, pfx: Path, password: str) -> None:
    key, cert, chain = pkcs12.load_key_and_certificates(pfx.read_bytes(), password.encode() or None)
    write(out, key, cert, chain or ())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--names", default="localhost")
    ap.add_argument("--pfx")
    ap.add_argument("--pfx-password", default="")
    a = ap.parse_args()
    if a.pfx:
        from_pfx(Path(a.out), Path(a.pfx), a.pfx_password)
    else:
        self_signed(Path(a.out), [n.strip() for n in a.names.split(",") if n.strip()] + ["localhost", "127.0.0.1"])
    print("ok")
