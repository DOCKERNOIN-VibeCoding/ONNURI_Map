# -*- coding: utf-8 -*-
"""
공공데이터포털에서 온누리상품권 가맹점 CSV 를 자동으로 내려받는다.

    python fetch_data.py            # data/ 에 최신 파일 저장
    python fetch_data.py --import   # 내려받고 바로 DB 에 적재

로그인·인증키 없이 받을 수 있다. 데이터가 갱신되면 첨부파일 ID 가 바뀌므로
데이터셋 페이지에서 매번 새로 읽어온다.
"""

import argparse
import os
import re
import sys

import requests

import onnuri_db

DATASET_URL = "https://www.data.go.kr/data/3060079/fileData.do"
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def find_file_id(session, dataset_url=DATASET_URL):
    """데이터셋 페이지에서 첨부파일 ID 를 찾는다."""
    res = session.get(dataset_url, timeout=30)
    res.raise_for_status()
    match = re.search(r"atchFileId=(FILE_\w+)&fileDetailSn=(\d+)", res.text)
    if not match:
        raise SystemExit(
            "데이터셋 페이지에서 다운로드 링크를 찾지 못했습니다.\n"
            f"사이트 구조가 바뀌었을 수 있습니다. 직접 받아주세요: {DATASET_URL}"
        )
    return match.group(1), match.group(2)


def filename_from(headers, fallback):
    """Content-Disposition 의 한글 파일명을 복원한다."""
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^";]+)"?', disposition)
    if not match:
        return fallback
    name = match.group(1)
    try:
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return re.sub(r'[\/:*?"<>|]', "_", name).strip()


def download(session, dataset_url=DATASET_URL, fallback="공공데이터.csv"):
    """데이터셋 페이지의 첨부 CSV 를 받아 (파일명, 내용) 으로 돌려준다."""
    file_id, detail_sn = find_file_id(session, dataset_url)
    res = session.get(
        DOWNLOAD_URL,
        params={"atchFileId": file_id, "fileDetailSn": detail_sn, "insertDataPrcus": "N"},
        headers={"Referer": dataset_url},
        timeout=180,
    )
    res.raise_for_status()
    if b"," not in res.content[:2000]:
        raise SystemExit("CSV 가 아닌 응답을 받았습니다. 잠시 후 다시 시도해 주세요.")
    return filename_from(res.headers, fallback), res.content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="내려받은 뒤 바로 DB 에 적재")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    print("데이터셋 페이지 확인 중…")
    name, content = download(session, fallback="온누리상품권_가맹점.csv")

    data_dir = os.path.join(onnuri_db.BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, name)

    with open(path, "wb") as f:
        f.write(content)
    print(f"저장 완료: {path}  ({len(content) / 1024 / 1024:.1f} MB)")

    if args.do_import:
        import import_csv
        import_csv.main(path)
    else:
        print(f'\n적재하려면: python import_csv.py "{path}"')


if __name__ == "__main__":
    sys.exit(main())
