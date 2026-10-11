"""Builds a UIDAI-style e-Aadhaar PDF for tests: text + photo, AES-256 password, CMS-signed by an openssl test chain."""
import io, os, re, subprocess

def run(*a, **k):
    return subprocess.run(list(a), check=True, capture_output=True, **k).stdout

def make_chain(tmp, signer_org="UNIQUE IDENTIFICATION AUTHORITY OF INDIA"):
    os.makedirs(f"{tmp}/trusted", exist_ok=True)
    cnf = f"{tmp}/ext.cnf"
    open(cnf, "w").write("[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n[leaf]\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,nonRepudiation\n")
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{tmp}/root.key", "-out", f"{tmp}/trusted/root.pem",
        "-days", "30", "-subj", "/C=IN/O=Test CCA/CN=Test CCA Root", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{tmp}/ca.key", "-out", f"{tmp}/ca.csr", "-subj", "/C=IN/O=Test Sub-CA/CN=Test Sub-CA for DSC")
    run("openssl", "x509", "-req", "-in", f"{tmp}/ca.csr", "-CA", f"{tmp}/trusted/root.pem", "-CAkey", f"{tmp}/root.key", "-CAcreateserial",
        "-out", f"{tmp}/ca.pem", "-days", "30", "-extfile", cnf, "-extensions", "ca")
    run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{tmp}/signer.key", "-out", f"{tmp}/signer.csr",
        "-subj", f"/C=IN/O={signer_org}/CN=DS Test Signer")
    run("openssl", "x509", "-req", "-in", f"{tmp}/signer.csr", "-CA", f"{tmp}/ca.pem", "-CAkey", f"{tmp}/ca.key", "-CAcreateserial",
        "-out", f"{tmp}/signer.pem", "-days", "30", "-extfile", cnf, "-extensions", "leaf")

def make_pdf(photo_path, gender="FEMALE", name="Asha Kumari", dob="15/06/1995", number="XXXX XXXX 1234"):
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["pdf.fonttype"] = 42
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(8.27, 5))
    fig.text(0.05, 0.9, "Government of India", fontsize=14)
    fig.text(0.35, 0.75, name, fontsize=12)
    fig.text(0.35, 0.68, f"DOB: {dob}", fontsize=12)
    fig.text(0.35, 0.61, gender, fontsize=12)
    fig.text(0.35, 0.45, number, fontsize=16)
    fig.text(0.35, 0.35, "VID : 9123 4567 8901 2345", fontsize=9)
    ax = fig.add_axes([0.05, 0.4, 0.25, 0.45]); ax.axis("off")
    ax.imshow(plt.imread(photo_path))
    buf = io.BytesIO(); fig.savefig(buf, format="pdf"); plt.close(fig)
    return buf.getvalue()

def encrypt(pdf, password):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    w.encrypt(user_password=password, owner_password=password + "-owner", algorithm="AES-256")
    out = io.BytesIO(); w.write(out); return out.getvalue()

def sign(pdf, tmp, placeholder=16384):
    """Incremental update with a /Sig dictionary whose ByteRange covers the whole file; CMS by openssl."""
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(pdf))
    tr = r.trailer
    size = int(tr["/Size"])
    root = tr.raw_get("/Root"); enc = tr.raw_get("/Encrypt")
    ids = tr.get("/ID")
    prev = int(re.findall(rb"startxref\s+(\d+)", pdf)[-1])
    base = pdf if pdf.endswith(b"\n") else pdf + b"\n"
    obj_off = len(base)
    br_placeholder = b"/ByteRange [0 0000000000 0000000000 0000000000]"
    obj = (f"{size} 0 obj\n<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached ".encode()
           + br_placeholder + b" /Contents <" + b"0" * placeholder + b"> >>\nendobj\n")
    xref_off = obj_off + len(obj)
    raw = lambda x: x.original_bytes if hasattr(x, "original_bytes") else bytes(x)  # noqa: E731
    idstr = "" if not ids else " /ID [<%s> <%s>]" % (raw(ids[0]).hex(), raw(ids[1]).hex())
    tail = (f"xref\n0 1\n0000000000 65535 f \n{size} 1\n{obj_off:010d} 00000 n \ntrailer\n<< /Size {size + 1} "
            f"/Root {root.idnum} {root.generation} R /Encrypt {enc.idnum} {enc.generation} R /Prev {prev}{idstr} >>\n"
            f"startxref\n{xref_off}\n%%EOF\n").encode()
    doc = base + obj + tail
    lt = doc.index(b"/Contents <", obj_off) + len(b"/Contents ")
    gt = lt + placeholder + 2
    br = b"/ByteRange [0 %010d %010d %010d]" % (lt, gt, len(doc) - gt)
    doc = doc.replace(br_placeholder, br, 1)
    open(f"{tmp}/tosign.bin", "wb").write(doc[:lt] + doc[gt:])
    cms = run("openssl", "cms", "-sign", "-binary", "-in", f"{tmp}/tosign.bin", "-signer", f"{tmp}/signer.pem", "-inkey", f"{tmp}/signer.key",
              "-certfile", f"{tmp}/ca.pem", "-outform", "DER", "-md", "sha256")
    hexsig = cms.hex().encode()
    assert len(hexsig) <= placeholder
    return doc[: lt + 1] + hexsig.ljust(placeholder, b"0") + doc[gt - 1 :]
