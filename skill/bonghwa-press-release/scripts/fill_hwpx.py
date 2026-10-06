#!/usr/bin/env python3
"""봉화군 보도자료 양식(hwpx)에 배포일자·제목·부제·본문을 채워 넣는 스크립트.

사용법
  # 1) 내장 기본 양식으로 바로 만들기 (--template 생략)
  python fill_hwpx.py --content 내용.json --out 보도자료_주제.hwpx

  # 2) 직접 받은 양식에 채우기
  python fill_hwpx.py --template 양식.hwpx --content 내용.json --out 보도자료_주제.hwpx

  # 3) 양식 구조 확인
  python fill_hwpx.py --template 양식.hwpx --dump

내용.json 형식 (contacts는 생략 가능, 생략하면 양식의 담당자 표를 그대로 둔다)
  {
    "date": "10. 7.(수)",
    "title": "봉화군, ...",
    "subtitle": "..., ...",
    "contacts": [
      {"직위": "도시계획과장", "성명": "○○○", "전화": "054)679-○○○○"},
      {"직위": "도시재생팀장", "성명": "○○○", "전화": "054)679-○○○○"},
      {"직위": "실무자",       "성명": "○○○", "전화": "054)679-○○○○"}
    ],
    "body": ["리드 문단", "둘째 문단", "...", "관계자 코멘트"]
  }
  contacts는 양식 담당자 표의 담당부서·작성자·실무자 줄 순서다(셋째 줄 직위는 보통 "실무자").

필요 패키지: lxml (pip install lxml)

양식이 .hwp(구형 바이너리)이면 한글에서 [다른 이름으로 저장 → 파일 형식: HWPX]로
저장한 뒤 사용한다. 한글이 없으면 tools/hwp2hwpx 의 변환기를 쓴다.
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import struct
import zipfile
import zlib

try:
    from lxml import etree
except ImportError:
    sys.exit("lxml이 필요합니다: pip install lxml")

DATE_RE = re.compile(r"^\s*[\d○]{1,2}\.\s*[\d○]{1,2}\.\s*\(.\)\s*$")
SECTION = "Contents/section0.xml"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "..", "templates", "press_release_template.hwpx")


def L(e):
    return etree.QName(e).localname


def text_of(p):
    return "".join(x.text or "" for x in p.iter() if L(x) == "t")


def remove_lineseg(p):
    for c in list(p):
        if L(c) == "linesegarray":
            p.remove(c)


def set_text(p, text, charpr=None):
    """문단의 첫 run·첫 t만 남기고 텍스트를 바꾼다. linesegarray는 반드시 지운다."""
    runs = [c for c in p if L(c) == "run"]
    if not runs:
        raise ValueError("run이 없는 문단입니다")
    for extra in runs[1:]:
        p.remove(extra)
    run = runs[0]
    if charpr:
        run.set("charPrIDRef", charpr)
    ts = [c for c in run if L(c) == "t"]
    if not ts:
        t = etree.SubElement(run, run.tag.replace("run", "t"))
        ts = [t]
    for extra in ts[1:]:
        run.remove(extra)
    ts[0].text = text
    for g in list(ts[0]):
        ts[0].remove(g)
    remove_lineseg(p)


def is_ole(path):
    with open(path, "rb") as f:
        return f.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def load(template):
    if is_ole(template):
        sys.exit(
            "이 파일은 구형 .hwp(바이너리)입니다. 한글에서 '다른 이름으로 저장 → HWPX'로 "
            "저장하거나 tools/hwp2hwpx 로 변환한 뒤 다시 실행하세요."
        )
    work = tempfile.mkdtemp(prefix="hwpx_")
    with zipfile.ZipFile(template) as zf:
        zf.extractall(work)
    tree = etree.parse(os.path.join(work, SECTION))
    return work, tree


def analyse(root):
    """양식에서 배포일자·제목·부제 문단과 본문 영역을 찾는다."""
    top = [c for c in root if L(c) == "p"]
    # 머리 표가 들어 있는 문단을 찾는다(양식 앞에 빈 문단이 있을 수 있다)
    header = next((p for p in top if any(L(x) == "tbl" for x in p.iter())), top[0])
    date_p = title_p = sub_p = None
    inner = [p for p in header.iter() if L(p) == "p" and p is not header
             and not any(L(x) == "tbl" for x in p.iter())]
    for p in inner:
        if date_p is None and DATE_RE.match(text_of(p).strip()):
            date_p = p
    # 1순위: "군정홍보에 많은 관심과 협조 감사드립니다." 다음의 비어 있지 않은 두 문단 = 제목, 부제
    idx = next((i for i, p in enumerate(inner) if "군정홍보" in text_of(p)), None)
    if idx is not None:
        after = [p for p in inner[idx + 1:] if text_of(p).strip()]
        if after:
            title_p = after[0]
        if len(after) > 1:
            sub_p = after[1]
    # 2순위: 앞뒤 하이픈이 붙은 부제("-…-")와 그 앞 문단
    if title_p is None or sub_p is None:
        for p in inner:
            s = text_of(p).strip()
            if s.startswith("-") and s.endswith("-") and len(s) > 2:
                sub_p = p
                sibs = [c for c in p.getparent() if L(c) == "p"]
                prev = [c for c in sibs[:sibs.index(p)] if text_of(c).strip()]
                title_p = prev[-1] if prev else None
                break
    body = top[top.index(header) + 1:]
    return header, date_p, title_p, sub_p, body


def contact_cells(header):
    """담당자 표의 (직위·성명 칸, 전화 칸) 문단을 담당부서·작성자·실무자 순서로 돌려준다."""
    tbl = next(x for x in header.iter() if L(x) == "tbl")
    cells = {}
    for tc in tbl.iter():
        if L(tc) != "tc":
            continue
        addr = next((c for c in tc if L(c) == "cellAddr"), None)
        if addr is None:
            continue
        ps = [p for p in tc.iter() if L(p) == "p"]
        if ps:
            cells.setdefault((int(addr.get("colAddr")), int(addr.get("rowAddr"))), ps[0])
    rows = []
    for row in range(3):
        name_p, tel_p = cells.get((3, row)), cells.get((4, row))
        if name_p is None or tel_p is None:
            break
        rows.append((name_p, tel_p))
    return rows


def dump(root):
    header, date_p, title_p, sub_p, body = analyse(root)
    for i, (n, t) in enumerate(contact_cells(header)):
        print(f"[담당자{i + 1}]  {text_of(n)!r} {text_of(t)!r}")
    print("[배포일자]", repr(text_of(date_p)) if date_p is not None else "찾지 못함")
    print("[제목]   ", repr(text_of(title_p)) if title_p is not None else "찾지 못함")
    print("[부제]   ", repr(text_of(sub_p)) if sub_p is not None else "찾지 못함")
    print(f"[본문]    최상위 문단 {len(body)}개")
    for i, p in enumerate(body):
        runs = [c.get("charPrIDRef") for c in p if L(c) == "run"]
        print(f"  {i:2d} charPr={runs} {text_of(p)[:60]!r}")


def fill(root, content):
    header, date_p, title_p, sub_p, body = analyse(root)
    if content.get("date"):
        if date_p is None:
            raise SystemExit("배포일자 문단을 찾지 못했습니다(예: '9. 8.(월)'). --dump로 확인하세요.")
        set_text(date_p, content["date"])
    if content.get("title"):
        if title_p is None:
            raise SystemExit("제목 문단을 찾지 못했습니다. --dump로 양식 구조를 확인하세요.")
        set_text(title_p, content["title"])
    if content.get("subtitle"):
        if sub_p is None:
            raise SystemExit("부제 문단을 찾지 못했습니다. --dump로 양식 구조를 확인하세요.")
        set_text(sub_p, content["subtitle"])

    contacts = content.get("contacts") or []
    if contacts:
        rows = contact_cells(header)
        if len(rows) < len(contacts):
            raise SystemExit(f"양식의 담당자 표는 {len(rows)}줄인데 contacts가 {len(contacts)}개입니다.")
        for (name_p, tel_p), c in zip(rows, contacts):
            title = (c.get("직위") or "").strip()
            name = (c.get("성명") or "").strip()
            # 원본 양식처럼 직위 길이와 상관없이 성명이 같은 위치에서 시작하도록 공백을 맞춘다
            # (한글 1자 = 공백 2칸, "도시계획과장" + 공백 5칸 = 17칸 기준)
            width = sum(2 if ord(ch) > 0x10FF else 1 for ch in title)
            set_text(name_p, (title + " " * max(1, 17 - width) + name) if name else title)
            if c.get("전화"):
                set_text(tel_p, c["전화"].strip())

    texts = content.get("body") or []
    if not texts:
        return
    filled = [p for p in body if text_of(p).strip()]
    empty = [p for p in body if not text_of(p).strip()]
    if not filled:
        raise SystemExit("본문 예시 문단을 찾지 못했습니다.")
    proto = filled[0]
    spacer = empty[0] if empty else None
    # 기본 본문 글자 모양: 빈 문단(간격용)의 글자 모양을 기준으로 삼는다
    base = None
    if spacer is not None:
        r = [c for c in spacer if L(c) == "run"]
        base = r[0].get("charPrIDRef") if r else None
    if base is None:
        base = [c for c in proto if L(c) == "run"][0].get("charPrIDRef")

    pos = list(root).index(body[0])
    proto_c = copy.deepcopy(proto)
    spacer_c = copy.deepcopy(spacer) if spacer is not None else None
    for p in body:
        root.remove(p)
    new = []
    for t in texts:
        if spacer_c is not None:
            new.append(copy.deepcopy(spacer_c))
        p = copy.deepcopy(proto_c)
        set_text(p, t, base)
        new.append(p)
    for i, p in enumerate(new):
        root.insert(pos + i, p)


def blank_png(w=724, h=1024):
    """미리보기 이미지를 덮어쓸 흰 PNG(외부 라이브러리 없이 생성)."""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def refresh_preview(work, root):
    """한글이 저장해 둔 미리보기(썸네일·텍스트)에는 양식의 이전 내용이 남아 있으므로 새 내용으로 바꾼다."""
    txt_path = os.path.join(work, "Preview", "PrvText.txt")
    if os.path.exists(txt_path):
        lines = [text_of(p) for p in root.iter() if L(p) == "p" and not any(L(x) == "p" for x in p.iterdescendants())]
        with open(txt_path, "w", encoding="utf-8", newline="") as f:
            f.write("\r\n".join(l for l in lines if l.strip()))
    img_path = os.path.join(work, "Preview", "PrvImage.png")
    if os.path.exists(img_path):
        with open(img_path, "wb") as f:
            f.write(blank_png())


def save(work, tree, out):
    refresh_preview(work, tree.getroot())
    tree.write(
        os.path.join(work, SECTION),
        xml_declaration=True,
        encoding=tree.docinfo.encoding or "UTF-8",
        standalone=tree.docinfo.standalone,
    )
    with zipfile.ZipFile(out, "w") as zf:
        mt = os.path.join(work, "mimetype")
        if os.path.exists(mt):
            zf.write(mt, "mimetype", compress_type=zipfile.ZIP_STORED)
        for dp, _, fns in os.walk(work):
            for fn in fns:
                fp = os.path.join(dp, fn)
                arc = os.path.relpath(fp, work).replace(os.sep, "/")
                if arc == "mimetype":
                    continue
                zf.write(fp, arc, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None, "ZIP 손상"
        etree.parse(zf.open(SECTION))


def main():
    ap = argparse.ArgumentParser(description="봉화군 보도자료 hwpx 양식 채우기")
    ap.add_argument("--template", help="양식 파일(.hwpx). 생략하면 내장 기본 양식을 쓴다")
    ap.add_argument("--content", help="내용 JSON 파일")
    ap.add_argument("--out", help="결과 파일(.hwpx)")
    ap.add_argument("--dump", action="store_true", help="양식 구조만 출력")
    a = ap.parse_args()

    template = a.template or DEFAULT_TEMPLATE
    if not os.path.exists(template):
        sys.exit(f"양식 파일이 없습니다: {template}\n--template으로 양식 경로를 지정하세요.")
    work, tree = load(template)
    try:
        root = tree.getroot()
        if a.dump or not a.content:
            dump(root)
            return
        with open(a.content, encoding="utf-8") as f:
            content = json.load(f)
        fill(root, content)
        out = a.out or "보도자료_결과.hwpx"
        save(work, tree, out)
        print("완료:", out)
        dump(etree.parse(zipfile.ZipFile(out).open(SECTION)).getroot())
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
