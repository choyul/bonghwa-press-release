#!/usr/bin/env python3
"""봉화군 보도자료 양식(hwpx)에 배포일자·제목·부제·본문을 채워 넣는 스크립트.

사용법
  # 1) 양식 구조 확인
  python fill_hwpx.py --template 양식.hwpx --dump

  # 2) 내용 채우기
  python fill_hwpx.py --template 양식.hwpx --content 내용.json --out 보도자료_주제.hwpx

내용.json 형식
  {
    "date": "10. 7.(수)",
    "title": "봉화군, ...",
    "subtitle": "-... -",
    "body": ["리드 문단", "둘째 문단", "...", "관계자 코멘트"]
  }

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
import zipfile

try:
    from lxml import etree
except ImportError:
    sys.exit("lxml이 필요합니다: pip install lxml")

DATE_RE = re.compile(r"^\s*\d{1,2}\.\s*\d{1,2}\.\s*\(.\)\s*$")
SECTION = "Contents/section0.xml"


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
    header = top[0]
    date_p = title_p = sub_p = None
    for p in header.iter():
        if L(p) != "p":
            continue
        s = text_of(p).strip()
        if date_p is None and DATE_RE.match(s):
            date_p = p
        if sub_p is None and s.startswith("-") and s.endswith("-") and len(s) > 2:
            sub_p = p
    if sub_p is not None:
        sibs = [c for c in sub_p.getparent() if L(c) == "p"]
        i = sibs.index(sub_p)
        for cand in reversed(sibs[:i]):
            if text_of(cand).strip():
                title_p = cand
                break
    body = top[1:]
    return header, date_p, title_p, sub_p, body


def dump(root):
    header, date_p, title_p, sub_p, body = analyse(root)
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
            raise SystemExit("제목 문단을 찾지 못했습니다. 부제가 '-…-' 형식인지 확인하세요.")
        set_text(title_p, content["title"])
    if content.get("subtitle"):
        if sub_p is None:
            raise SystemExit("부제 문단을 찾지 못했습니다(앞뒤 하이픈 '-…-' 형식).")
        set_text(sub_p, content["subtitle"])

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


def save(work, tree, out):
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
    ap.add_argument("--template", required=True, help="양식 파일(.hwpx)")
    ap.add_argument("--content", help="내용 JSON 파일")
    ap.add_argument("--out", help="결과 파일(.hwpx)")
    ap.add_argument("--dump", action="store_true", help="양식 구조만 출력")
    a = ap.parse_args()

    work, tree = load(a.template)
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
