import streamlit as st
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from pdf2image import convert_from_bytes
import pandas as pd
import re
import io
import os
from difflib import SequenceMatcher


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(
    page_title="OCR 파일명 생성기",
    page_icon="📄",
    layout="wide"
)

st.title("📄 OCR 파일명 자동 생성기")
st.caption("수주번호 · 의뢰일자 · 업체명 · 발주서번호를 자동 인식하여 파일명을 생성합니다.")


# =========================================================
# OCR 설정
# =========================================================

OCR_LANG = "kor+eng"

# 문서에서 찾을 라벨
LABEL_GROUPS = {
    "order_no": [
        "수주번호",
        "수주 번호",
        "Order No",
        "OrderNo",
        "Order Number",
        "OrderNumber"
    ],

    "date": [
        "의뢰일자",
        "의뢰 일자",
        "Issue Date",
        "IssueDate",
        "Request Date",
        "RequestDate"
    ],

    "vendor": [
        "업체명",
        "업체 명",
        "업체소재지",
        "업체 소재지",
        "Vendor",
        "Vendor Name",
        "VendorName",
        "Supplier",
        "Supplier Name",
        "SupplierName"
    ],

    "po_no": [
        "발주서번호",
        "발주서 번호",
        "PO No",
        "P.O. No",
        "PONo",
        "PO Number",
        "PONumber"
    ]
}


# =========================================================
# 문자열 처리
# =========================================================

def normalize_text(text):
    """
    OCR 문자열 비교용 정규화
    - 공백 제거
    - 특수문자 일부 제거
    - 영문 대문자화
    """
    if text is None:
        return ""

    text = str(text)

    text = text.replace("\n", "")
    text = text.replace("\r", "")
    text = text.replace(" ", "")
    text = text.replace("\t", "")

    return text.upper()


def clean_text(text):
    if text is None:
        return ""

    text = str(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =========================================================
# 이미지 전처리
# =========================================================

def preprocess_images(image):
    """
    한 장의 원본 이미지에서 여러 OCR용 이미지를 생성.
    위치가 달라지는 문서를 고려하여 고정 좌표는 사용하지 않음.
    """

    results = []

    # 원본
    results.append(("original", image))

    # grayscale + contrast
    gray = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(gray).enhance(1.8)
    results.append(("gray_contrast", contrast))

    # 조금 선명하게
    sharp = contrast.filter(ImageFilter.SHARPEN)
    results.append(("sharp", sharp))

    # threshold
    threshold = contrast.point(
        lambda x: 255 if x > 170 else 0
    )
    results.append(("threshold", threshold))

    # 확대
    w, h = image.size

    # 너무 작은 이미지만 확대
    if w < 1800:
        scale = 2
        enlarged = image.resize(
            (w * scale, h * scale),
            Image.Resampling.LANCZOS
        )

        results.append(("enlarged", enlarged))

        gray2 = ImageOps.grayscale(enlarged)
        contrast2 = ImageEnhance.Contrast(gray2).enhance(1.8)
        results.append(("enlarged_contrast", contrast2))

    return results


# =========================================================
# OCR 실행
# =========================================================

def run_ocr_data(image, psm=6):
    """
    Tesseract의 word-level OCR 결과를 DataFrame으로 가져옴.
    각 단어의 left/top/width/height/confidence를 사용.
    """

    config = f"--oem 1 --psm {psm}"

    try:
        data = pytesseract.image_to_data(
            image,
            lang=OCR_LANG,
            config=config,
            output_type=pytesseract.Output.DATAFRAME
        )

        if data is None:
            return pd.DataFrame()

        data = data.dropna(subset=["text"])

        data["text"] = data["text"].astype(str).str.strip()

        data = data[data["text"] != ""]

        # 숫자로 변환
        for col in ["left", "top", "width", "height", "conf"]:
            data[col] = pd.to_numeric(
                data[col],
                errors="coerce"
            )

        data = data.dropna(
            subset=["left", "top", "width", "height"]
        )

        return data

    except Exception:
        return pd.DataFrame()


# =========================================================
# OCR 결과에서 LINE 만들기
# =========================================================

def build_lines(data):
    """
    Tesseract가 준 block/par/line 번호를 이용해
    실제 문서의 한 줄 단위로 묶음.

    고정 좌표를 사용하지 않고 OCR 결과 자체의 좌표를 이용함.
    """

    if data.empty:
        return []

    group_cols = [
        "page_num",
        "block_num",
        "par_num",
        "line_num"
    ]

    lines = []

    for _, group in data.groupby(group_cols):

        group = group.sort_values("left")

        words = []

        for _, row in group.iterrows():

            text = clean_text(row["text"])

            if not text:
                continue

            words.append({
                "text": text,
                "x": float(row["left"]),
                "y": float(row["top"]),
                "w": float(row["width"]),
                "h": float(row["height"]),
                "conf": float(row["conf"])
            })

        if not words:
            continue

        line_text = " ".join(
            word["text"] for word in words
        )

        lines.append({
            "text": line_text,
            "words": words,
            "x": min(w["x"] for w in words),
            "y": min(w["y"] for w in words),
            "right": max(w["x"] + w["w"] for w in words),
            "bottom": max(w["y"] + w["h"] for w in words)
        })

    lines.sort(key=lambda x: (x["y"], x["x"]))

    return lines


# =========================================================
# 라벨 찾기
# =========================================================

def similarity(a, b):
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0

    return SequenceMatcher(None, a, b).ratio()


def find_label_in_line(line, labels):
    """
    한 줄에서 라벨을 찾음.

    예:
    "업체명 신진볼텍"
    "Issue Date 2025-04-16"
    "Order No H250208UD-1"

    같은 줄에서 라벨의 위치를 찾아
    오른쪽 값을 가져올 수 있도록 함.
    """

    words = line["words"]

    best = None

    # 1~4개 단어를 묶어서 라벨 검색
    for start in range(len(words)):

        for count in range(1, min(5, len(words) - start + 1)):

            selected = words[start:start + count]

            candidate_text = "".join(
                w["text"] for w in selected
            )

            candidate_norm = normalize_text(candidate_text)

            if not candidate_norm:
                continue

            for label in labels:

                label_norm = normalize_text(label)

                # 완전 포함
                if label_norm in candidate_norm:
                    score = 1.0

                else:
                    score = similarity(
                        candidate_norm,
                        label_norm
                    )

                # 너무 짧은 것은 제외
                if score < 0.72:
                    continue

                x1 = selected[0]["x"]
                x2 = (
                    selected[-1]["x"]
                    + selected[-1]["w"]
                )

                item = {
                    "score": score,
                    "x1": x1,
                    "x2": x2,
                    "words_after": words[start + count:],
                    "matched_text": candidate_text,
                    "label": label
                }

                if best is None or score > best["score"]:
                    best = item

    return best


# =========================================================
# 다른 라벨인지 확인
# =========================================================

ALL_LABELS = []

for values in LABEL_GROUPS.values():
    ALL_LABELS.extend(values)


def looks_like_label(text):
    norm = normalize_text(text)

    if not norm:
        return False

    for label in ALL_LABELS:
        label_norm = normalize_text(label)

        if label_norm in norm:
            return True

        if similarity(norm, label_norm) >= 0.82:
            return True

    return False


# =========================================================
# 라벨 오른쪽 값 추출
# =========================================================

def extract_same_line_value(line, label_info, field_type):
    """
    라벨과 같은 줄에서 오른쪽에 있는 값을 추출.

    가장 중요한 부분:
    업체명이 문서마다 위치가 달라도
    '업체명'이라는 OCR 위치를 기준으로 오른쪽을 찾음.
    """

    after_words = label_info["words_after"]

    if not after_words:
        return ""

    selected = []

    for word in after_words:

        text = clean_text(word["text"])

        if not text:
            continue

        # 다음 필드 라벨이 나오면 중지
        if looks_like_label(text):
            break

        # 지나치게 왼쪽에 있는 경우 제외
        if word["x"] + word["w"] <= label_info["x2"]:
            continue

        selected.append(text)

    if not selected:
        return ""

    value = " ".join(selected)

    value = clean_text(value)

    return value


# =========================================================
# 값 정리
# =========================================================

def normalize_date(value):
    """
    날짜를 YYYYMMDD로 변환.
    """

    if not value:
        return ""

    text = value

    # OCR에서 흔한 구분자 제거
    text = text.replace(".", "-")
    text = text.replace("/", "-")
    text = text.replace("_", "-")

    # 2025-04-16
    m = re.search(
        r"(20\d{2})[-\s]?(\d{1,2})[-\s]?(\d{1,2})",
        text
    )

    if m:
        year = m.group(1)
        month = m.group(2).zfill(2)
        day = m.group(3).zfill(2)

        return f"{year}{month}{day}"

    # 20250416
    m = re.search(
        r"(20\d{2})(\d{2})(\d{2})",
        text
    )

    if m:
        return "".join(m.groups())

    return ""


def normalize_code(value, field_type):
    """
    수주번호 / PO 번호 정리.

    OCR 오인식은 너무 공격적으로 수정하지 않음.
    """

    if not value:
        return ""

    text = clean_text(value)

    # 불필요한 앞뒤 기호 제거
    text = text.strip(" :;,.|[](){}")

    if field_type == "order_no":

        # Order No 뒤의 불필요한 문자 제거
        text = re.sub(
            r"^(ORDER\s*NO\.?|수주번호)\s*[:\-]?\s*",
            "",
            text,
            flags=re.I
        )

    elif field_type == "po_no":

        text = re.sub(
            r"^(P\.?\s*O\.?\s*NO\.?|발주서번호)\s*[:\-]?\s*",
            "",
            text,
            flags=re.I
        )

    return text.strip()


# =========================================================
# 업체명 전용 정리
# =========================================================

ADDRESS_WORDS = [
    "대한민국",
    "대한민국시",
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원도",
    "충청북도",
    "충청남도",
    "전라북도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
    "시",
    "군",
    "구",
    "읍",
    "면",
    "동",
    "리",
    "로",
    "길",
    "번길",
    "대로"
]


def company_score(text, conf=50):
    """
    업체명 후보 점수.

    업체 목록을 미리 지정하지 않음.
    """

    if not text:
        return -999

    score = 0

    # 신뢰도
    score += min(max(conf, 0), 100) * 0.25

    # 한글/영문 포함
    if re.search(r"[가-힣]", text):
        score += 20

    if re.search(r"[A-Za-z]", text):
        score += 10

    # 업체명에서 자주 보이는 표현
    company_words = [
        "주식회사",
        "(주)",
        "㈜",
        "CO",
        "CORP",
        "INC",
        "LTD",
        "INDUSTRY",
        "INDUSTRIAL",
        "TECH",
        "TECHNOLOGY",
        "산업",
        "공업",
        "상사",
        "정밀",
        "기공",
        "볼트",
        "테크",
        "머티리얼",
        "머티리얼스"
    ]

    upper = text.upper()

    for word in company_words:
        if word.upper() in upper:
            score += 25
            break

    # 주소 단어가 많이 들어간 후보는 감점
    for word in ADDRESS_WORDS:
        if word in text:
            score -= 20

    # 숫자가 많이 들어간 것은 업체명일 가능성이 낮음
    digits = len(re.findall(r"\d", text))

    if digits >= 4:
        score -= 25

    # 너무 짧으면 감점
    if len(normalize_text(text)) <= 1:
        score -= 30

    return score


def clean_company_name(text):
    """
    업체명에 섞일 수 있는 불필요한 부분 제거.
    """

    if not text:
        return ""

    text = clean_text(text)

    # 주소가 시작되는 경우 이후 제거
    for addr in ADDRESS_WORDS:

        pos = text.find(addr)

        if pos > 0:
            text = text[:pos].strip()
            break

    # 끝의 콜론/쉼표 등 제거
    text = text.strip(" :;,./|")

    # 중복 공백
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# 업체명 찾기
# =========================================================

def extract_vendor(lines):
    """
    업체 목록을 사용하지 않음.

    1순위:
        '업체명' / 'Vendor' 등의 라벨 오른쪽 같은 줄

    2순위:
        라벨 바로 아래/주변의 OCR 단어

    주소처럼 보이는 값은 감점.
    """

    candidates = []

    vendor_labels = LABEL_GROUPS["vendor"]

    for line_index, line in enumerate(lines):

        label_info = find_label_in_line(
            line,
            vendor_labels
        )

        if label_info:

            # -----------------------------
            # 1. 같은 줄 오른쪽
            # -----------------------------
            same_line = extract_same_line_value(
                line,
                label_info,
                "vendor"
            )

            if same_line:

                score = company_score(
                    same_line,
                    sum(
                        w["conf"]
                        for w in label_info["words_after"]
                    ) / max(
                        len(label_info["words_after"]),
                        1
                    )
                )

                candidates.append({
                    "value": clean_company_name(same_line),
                    "score": score + 50,
                    "reason": "업체명 라벨 오른쪽"
                })

            # -----------------------------
            # 2. 같은 줄의 오른쪽 단어들 개별 후보
            # -----------------------------
            for word in label_info["words_after"]:

                text = clean_company_name(
                    word["text"]
                )

                if not text:
                    continue

                score = company_score(
                    text,
                    word["conf"]
                )

                candidates.append({
                    "value": text,
                    "score": score + 35,
                    "reason": "업체명 라벨 오른쪽 단어"
                })

            # -----------------------------
            # 3. 바로 다음 1~2줄
            # -----------------------------
            for offset in [1, 2]:

                idx = line_index + offset

                if idx >= len(lines):
                    continue

                next_line = lines[idx]

                vertical_gap = (
                    next_line["y"] - line["bottom"]
                )

                # 너무 멀리 떨어져 있으면 제외
                if vertical_gap > 180:
                    continue

                for word in next_line["words"]:

                    text = clean_company_name(
                        word["text"]
                    )

                    if not text:
                        continue

                    # 라벨보다 오른쪽 또는 비슷한 영역
                    if word["x"] < label_info["x1"] - 50:
                        continue

                    score = company_score(
                        text,
                        word["conf"]
                    )

                    # 아래 줄은 우선순위를 낮춤
                    score -= 20

                    candidates.append({
                        "value": text,
                        "score": score,
                        "reason": "업체명 라벨 주변"
                    })

    # 빈 값 제거
    candidates = [
        c for c in candidates
        if c["value"]
    ]

    if not candidates:
        return ""

    # 점수순 정렬
    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    best = candidates[0]

    # 너무 자신 없는 결과는 빈 값
    if best["score"] < 25:
        return ""

    return best["value"]


# =========================================================
# 일반 필드 찾기
# =========================================================

def extract_field(lines, field_type):
    """
    날짜 / 수주번호 / PO 번호 추출.
    """

    labels = LABEL_GROUPS[field_type]

    candidates = []

    for line_index, line in enumerate(lines):

        label_info = find_label_in_line(
            line,
            labels
        )

        if not label_info:
            continue

        # 같은 줄 오른쪽
        value = extract_same_line_value(
            line,
            label_info,
            field_type
        )

        if value:

            candidates.append({
                "value": value,
                "score": label_info["score"] + 50
            })

        # 바로 다음 줄도 확인
        for offset in [1, 2]:

            idx = line_index + offset

            if idx >= len(lines):
                continue

            next_line = lines[idx]

            vertical_gap = (
                next_line["y"] - line["bottom"]
            )

            if vertical_gap > 180:
                continue

            # 다음 줄 전체
            next_text = next_line["text"]

            candidates.append({
                "value": next_text,
                "score": label_info["score"] + 10
            })

    if not candidates:
        return ""

    # =====================================================
    # 날짜
    # =====================================================
    if field_type == "date":

        for candidate in sorted(
            candidates,
            key=lambda x: x["score"],
            reverse=True
        ):

            date_value = normalize_date(
                candidate["value"]
            )

            if date_value:
                return date_value

        return ""

    # =====================================================
    # 수주번호
    # =====================================================
    if field_type == "order_no":

        valid = []

        for candidate in candidates:

            value = normalize_code(
                candidate["value"],
                "order_no"
            )

            # 영문/숫자가 포함된 코드만
            if re.search(
                r"[A-Za-z0-9]",
                value
            ):

                # 너무 긴 문장은 제외
                if len(value) <= 40:
                    valid.append(
                        (
                            candidate["score"],
                            value
                        )
                    )

        if valid:

            valid.sort(
                key=lambda x: x[0],
                reverse=True
            )

            return valid[0][1]

        return ""

    # =====================================================
    # PO 번호
    # =====================================================
    if field_type == "po_no":

        valid = []

        for candidate in candidates:

            value = normalize_code(
                candidate["value"],
                "po_no"
            )

            if re.search(
                r"[A-Za-z0-9]",
                value
            ):

                if len(value) <= 50:
                    valid.append(
                        (
                            candidate["score"],
                            value
                        )
                    )

        if valid:

            valid.sort(
                key=lambda x: x[0],
                reverse=True
            )

            return valid[0][1]

        return ""

    return ""


# =========================================================
# 전체 OCR 분석
# =========================================================

def analyze_image(image):
    """
    여러 전처리 + PSM으로 OCR을 실행하고
    가장 신뢰도 높은 결과를 선택.
    """

    all_results = []

    variants = preprocess_images(image)

    for variant_name, variant_image in variants:

        for psm in [6, 11]:

            data = run_ocr_data(
                variant_image,
                psm=psm
            )

            if data.empty:
                continue

            lines = build_lines(data)

            if not lines:
                continue

            result = {
                "variant": variant_name,
                "psm": psm,
                "lines": lines,
                "data": data
            }

            all_results.append(result)

    if not all_results:
        return {
            "order_no": "",
            "date": "",
            "vendor": "",
            "po_no": "",
            "raw_text": "",
            "lines": []
        }

    # 각 OCR 결과별 필드 추출
    field_results = []

    for result in all_results:

        lines = result["lines"]

        order_no = extract_field(
            lines,
            "order_no"
        )

        date = extract_field(
            lines,
            "date"
        )

        vendor = extract_vendor(
            lines
        )

        po_no = extract_field(
            lines,
            "po_no"
        )

        field_results.append({
            "order_no": order_no,
            "date": date,
            "vendor": vendor,
            "po_no": po_no,
            "variant": result["variant"],
            "psm": result["psm"],
            "lines": lines
        })

    # =====================================================
    # 여러 OCR 결과 중 각 필드별로 가장 많이 나온 값 선택
    # =====================================================

    def choose_most_common(field):

        values = []

        for r in field_results:

            value = clean_text(
                r.get(field, "")
            )

            if value:
                values.append(value)

        if not values:
            return ""

        # 날짜는 정규화
        if field == "date":
            normalized = []

            for value in values:

                d = normalize_date(value)

                if d:
                    normalized.append(d)

            values = normalized

            if not values:
                return ""

        # 동일 값 빈도
        counts = {}

        for value in values:

            counts[value] = (
                counts.get(value, 0) + 1
            )

        # 빈도가 높은 값
        sorted_values = sorted(
            counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_values[0][0]

    final_order = choose_most_common(
        "order_no"
    )

    final_date = choose_most_common(
        "date"
    )

    final_vendor = choose_most_common(
        "vendor"
    )

    final_po = choose_most_common(
        "po_no"
    )

    # 대표 OCR 결과
    best_result = field_results[0]

    raw_text = "\n".join(
        line["text"]
        for line in best_result["lines"]
    )

    return {
        "order_no": final_order,
        "date": final_date,
        "vendor": final_vendor,
        "po_no": final_po,
        "raw_text": raw_text,
        "lines": best_result["lines"]
    }


# =========================================================
# 파일 → 이미지
# =========================================================

def load_images(uploaded_file):

    file_name = uploaded_file.name.lower()

    file_bytes = uploaded_file.read()

    # PDF
    if file_name.endswith(".pdf"):

        try:

            pages = convert_from_bytes(
                file_bytes,
                dpi=300
            )

            return pages

        except Exception as e:

            st.error(
                f"PDF 변환 오류: {e}"
            )

            return []

    # 이미지
    else:

        try:

            image = Image.open(
                io.BytesIO(file_bytes)
            )

            return [image.convert("RGB")]

        except Exception as e:

            st.error(
                f"이미지 읽기 오류: {e}"
            )

            return []


# =========================================================
# 파일명 생성
# =========================================================

def make_filename(
    order_no,
    date,
    vendor,
    po_no
):

    parts = [
        order_no,
        date,
        vendor,
        po_no
    ]

    # 파일명에 사용할 수 없는 문자 제거
    cleaned = []

    for part in parts:

        part = clean_text(part)

        part = re.sub(
            r'[\\/:*?"<>|]',
            "",
            part
        )

        cleaned.append(part)

    return "_".join(cleaned)


# =========================================================
# 화면
# =========================================================

uploaded_file = st.file_uploader(
    "PDF 또는 이미지 파일을 올려주세요.",
    type=[
        "pdf",
        "png",
        "jpg",
        "jpeg"
    ]
)


if uploaded_file:

    st.write(
        f"📎 파일명: **{uploaded_file.name}**"
    )

    if st.button(
        "🔍 OCR 분석 시작",
        type="primary"
    ):

        with st.spinner(
            "문서를 분석하고 있습니다..."
        ):

            images = load_images(
                uploaded_file
            )

            if not images:

                st.error(
                    "문서를 읽을 수 없습니다."
                )

            else:

                # 현재는 첫 페이지 기준
                image = images[0]

                result = analyze_image(
                    image
                )

                st.session_state["ocr_result"] = result


# =========================================================
# 결과 표시
# =========================================================

if "ocr_result" in st.session_state:

    result = st.session_state["ocr_result"]

    st.subheader("📋 OCR 인식 결과")

    col1, col2 = st.columns(2)

    with col1:

        order_no = st.text_input(
            "① 수주번호",
            value=result["order_no"]
        )

        date = st.text_input(
            "② 의뢰일자",
            value=result["date"]
        )

    with col2:

        vendor = st.text_input(
            "③ 업체명",
            value=result["vendor"]
        )

        po_no = st.text_input(
            "④ 발주서번호",
            value=result["po_no"]
        )

    st.divider()

    filename = make_filename(
        order_no,
        date,
        vendor,
        po_no
    )

    st.subheader("📁 생성 파일명")

    st.code(
        filename,
        language=None
    )

    # 복사 버튼
    st.components.v1.html(
        f"""
        <button
            onclick="navigator.clipboard.writeText('{filename}')"
            style="
                width:100%;
                padding:12px;
                font-size:16px;
                font-weight:bold;
                cursor:pointer;
            "
        >
        📋 파일명 복사
        </button>
        """,
        height=55
    )

    st.divider()

    # 인식 결과 확인
    with st.expander(
        "🔎 OCR 원문 확인"
    ):

        st.text(
            result["raw_text"]
        )

    # 안내
    st.caption(
        "※ OCR 결과가 잘못된 경우 위 4개 항목을 직접 수정하면 "
        "파일명에 바로 반영됩니다."
    )
