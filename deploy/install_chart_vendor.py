"""Install the pinned official standalone chart distribution, without npm or runtime CDN."""
import hashlib
import io
import tarfile
import urllib.request
from pathlib import Path

URL="https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-5.0.9.tgz"
SHA256="358e037fd752ff4c3e34928ce0ab7c94a72f9915f6383b7dc1bb10e6840a7abf"
NOTICE="TradingView Lightweight Charts™\nCopyright (с) 2025 TradingView, Inc. https://www.tradingview.com/\n"

def main():
    with urllib.request.urlopen(URL,timeout=30) as response:
        data=response.read(3_000_000)
    if hashlib.sha256(data).hexdigest()!=SHA256:
        raise RuntimeError("Chart package digest mismatch")
    directory=Path(__file__).resolve().parents[1]/"recover_trading"/"dashboard_static"/"vendor"
    directory.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as archive:
        for source,dest in (("package/dist/lightweight-charts.standalone.production.js","lightweight-charts.js"),("package/LICENSE","LICENSE")):
            with archive.extractfile(source) as file:
                payload=file.read()
            temp=directory/(dest+".tmp")
            temp.write_bytes(payload)
            temp.replace(directory/dest)
    (directory/"NOTICE").write_text(NOTICE,encoding="utf-8")
    print("Installed verified TradingView Lightweight Charts 5.0.9")

if __name__=="__main__":
    main()
