import base64
import datetime
from OpenSSL import crypto


CTL_LISTS = 'https://www.gstatic.com/ct/log_list/log_list.json'

CTL_INFO = "http://{}/ct/v1/get-sth"

DOWNLOAD = "http://{}/ct/v1/get-entries?start={}&end={}"

from construct import Struct, Byte, Int16ub, Int64ub, Enum, Bytes, Int24ub, this, GreedyBytes, GreedyRange, Terminated, Embedded

MerkleTreeHeader = Struct(
    "Version"         / Byte,
    "MerkleLeafType"  / Byte,
    "Timestamp"       / Int64ub,
    "LogEntryType"    / Enum(Int16ub, X509LogEntryType=0, PrecertLogEntryType=1),
    "Entry"           / GreedyBytes
)

Certificate = Struct(
    "Length" / Int24ub,
    "CertData" / Bytes(this.Length)
)

CertificateChain = Struct(
    "ChainLength" / Int24ub,
    "Chain" / GreedyRange(Certificate),
)

PreCertEntry = Struct(
    "LeafCert" / Certificate,
    Embedded(CertificateChain),
    Terminated
)


def add_all_domains(cert_data):
    all_domains = []

    # Apparently we have certificates with null CNs....what?
    if cert_data['subject'].get('CN', ''):
        all_domains.append(cert_data['subject']['CN'].lower())

    SAN = cert_data['extensions'].get('subjectAltName', '')

    if SAN:
        for entry in SAN.split(', '):
            if entry.startswith('DNS:'):
                all_domains.append(entry.replace('DNS:', '').lower())

    return all_domains


def dump_cert(certificate):
    subject = certificate.get_subject()
    not_before = datetime.datetime.strptime(certificate.get_notBefore().decode('ascii'), "%Y%m%d%H%M%SZ").timestamp()
    not_after = datetime.datetime.strptime(certificate.get_notAfter().decode('ascii'), "%Y%m%d%H%M%SZ").timestamp()

    return {
        "subject": {
            "aggregated": repr(certificate.get_subject())[18:-2],
            "C": subject.C,
            "ST": subject.ST,
            "L": subject.L,
            "O": subject.O,
            "OU": subject.OU,
            "CN": subject.CN
        },
        "extensions": dump_extensions(certificate),
        "not_before": not_before,
        "not_after": not_after,
        "as_der": base64.b64encode(crypto.dump_certificate(crypto.FILETYPE_ASN1, certificate)).decode('utf-8')
    }


def dump_extensions(certificate):
    extensions = {}
    for x in range(certificate.get_extension_count()):
        extension_name = ""
        try:
            extension_name = certificate.get_extension(x).get_short_name()
            if extension_name != b'UNDEF':
                extensions[extension_name.decode('latin-1')] = certificate.get_extension(x).__str__()
        except IndexError:
            # IndexError raised when trying to access unknown cert
            pass
        except (crypto.Error, UnicodeDecodeError):
            # crypto.error raised when found by OpenSSL, but PyOpenSSL has no parsing logic
            # UnicodeDecodeError raised when unable to decode cert extension
            try:
                extensions[extension_name.decode('latin-1')] = "NULL"
            except UnicodeDecodeError:
                pass
    return extensions
