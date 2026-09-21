import streamlit as st
import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import re
import os
import io
from difflib import SequenceMatcher


# ============================================================
# 기본 설정
# ============================================================

os.environ["PATH"] += os.pathsep + "/usr/bin"

st.set_page_config(
    page_title="인수검사서 파일명 자동 생성기",
    page_icon="📄",
    layout="centered"
)

st.title("📄 인수검사서 파일명 자동 생성기")
st.write(
    "스캔된 PDF 또는 이미지에서 수주번호, 의뢰일자, 업체명, 발주서번호를 자동 추출합니다."
)

st.markdown("---")


# ============================================================
# 알려진 업체명
# ============================================================

KNOWN_VENDORS = [
    "신진볼텍",
    "동남볼트",
    "일신피티에프이",
    "에스엔피머티리얼",
]


# ============================================================
# 이미지 전처리
# ============================================================

def make_ocr_images(image):
    """
    스캔본 상태가 제각각이므로 여러 방식으로 OCR용 이미지를 만든다.
    좌표는 사용하지 않는다.
    """

    original = image.convert("RGB")

    gray = ImageOps.grayscale(original)

    # 2.5배 확대
    w, h = gray.size
    enlarged = gray.resize(
        (int(w * 2.5), int(h * 2.5)),
        Image.Resampling.LANCZOS
    )

    # 대비 강화
    contrast = ImageEnhance.Contrast(enlarged).enhance(1.8)

    # 선명도 강화
    sharp = contrast.filter(ImageFilter.SHARPEN)

    # 흑백화
    threshold = sharp.point(
        lambda p: 255 if p > 175 else 0
    )

    return [
        original,
        enlarged,
        sharp,
        threshold
    ]


# ============================================================
# OCR 데이터 읽기
# ============================================================

def get_ocr_data(image, psm=6):

    config = f"--oem 3 --psm {psm}"

    try:
        data = pytesseract.image_to_data(
            image,
            lang="kor+eng",
            config=config,
            output_type=Output.DICT
        )

        words = []

        count = len(data["text"])

        for i in range(count):

            text = data["text"][i].strip()

            if not text:
                continue

            try:
                conf = float(data["conf"][i])
            except:
                conf = 0

            if conf < 5:
                continue

            words.append({
                "text": text,
                "conf": conf,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "right": int(data["left"][i]) + int(data["width"][i]),
                "bottom": int(data["top"][i]) + int(data["height"][i]),
                "block": data["block_num"][i],
                "par": data["par_num"][i],
                "line": data["line_num"][i],
            })

        return words

    except Exception:
        return []


# ============================================================
# OCR 전체 텍스트
# ============================================================

def get_ocr_text(image):

    try:
        return pytesseract.image_to_string(
            image,
            lang="kor+eng",
            config="--oem 3 --psm 6"
        )
    except:
        return ""


# ============================================================
# OCR 단어들을 줄 단위로 묶기
# ============================================================

def group_words_into_lines(words):

    lines = {}

    for word in words:

        key = (
            word["block"],
            word["par"],
            word["line"]
        )

        if key not in lines:
            lines[key] = []

        lines[key].append(word)

    result = []

    for key, line_words in lines.items():

        line_words.sort(
            key=lambda x: x["left"]
        )

        text = " ".join(
            w["text"]
            for w in line_words
        )

        result.append({
            "words": line_words,
            "text": text,
            "top": min(w["top"] for w in line_words),
            "bottom": max(w["bottom"] for w in line_words),
            "left": min(w["left"] for w in line_words),
            "right": max(w["right"] for w in line_words),
        })

    result.sort(
        key=lambda x: (x["top"], x["left"])
    )

    return result


# ============================================================
# 문자열 정규화
# ============================================================

def compact_text(text):

    if not text:
        return ""

    text = text.upper()

    text = text.replace(" ", "")
    text = text.replace("\n", "")
    text = text.replace("\t", "")

    return text


# ============================================================
# OCR 라벨 유사도
# ============================================================

def similarity(a, b):

    a = compact_text(a)
    b = compact_text(b)

    if not a or not b:
        return 0

    if a in b or b in a:
        return 1.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# 라벨을 찾는다
# ============================================================

def find_label(words, labels):

    """
    OCR 결과에서 지정한 라벨을 찾는다.

    예:
    Issue Date
    의뢰일자
    Order No
    수주번호
    PO No
    업체소재지
    Vendor Address
    """

    candidates = []

    # --------------------------------------------------------
    # 개별 단어 검색
    # --------------------------------------------------------

    for word in words:

        for label in labels:

            score = similarity(
                word["text"],
                label
            )

            if score >= 0.72:

                candidates.append({
                    "word": word,
                    "score": score
                })


    # --------------------------------------------------------
    # 연속된 2~4개 단어 조합 검색
    # 예:
    # Vendor + Address
    # Issue + Date
    # Order + No
    # --------------------------------------------------------

    sorted_words = sorted(
        words,
        key=lambda x: (x["top"], x["left"])
    )

    for i in range(len(sorted_words)):

        for n in range(2, 5):

            if i + n > len(sorted_words):
                continue

            group = sorted_words[i:i+n]

            # 같은 줄에 있는 단어만
            if len({
                (
                    x["block"],
                    x["par"],
                    x["line"]
                )
                for x in group
            }) != 1:
                continue

            combined = "".join(
                x["text"]
                for x in group
            )

            combined_space = " ".join(
                x["text"]
                for x in group
            )

            for label in labels:

                score1 = similarity(
                    combined,
                    label
                )

                score2 = similarity(
                    combined_space,
                    label
                )

                score = max(
                    score1,
                    score2
                )

                if score >= 0.72:

                    candidates.append({
                        "word": {
                            "text": combined,
                            "left": min(
                                x["left"]
                                for x in group
                            ),
                            "right": max(
                                x["right"]
                                for x in group
                            ),
                            "top": min(
                                x["top"]
                                for x in group
                            ),
                            "bottom": max(
                                x["bottom"]
                                for x in group
                            ),
                            "height": max(
                                x["height"]
                                for x in group
                            ),
                            "block": group[0]["block"],
                            "par": group[0]["par"],
                            "line": group[0]["line"],
                        },
                        "score": score
                    })

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return candidates[0]["word"]


# ============================================================
# 라벨 주변의 단어 찾기
# ============================================================

def words_near_label(
    words,
    label,
    max_vertical_lines=2
):

    if not label:
        return []

    label_center_y = (
        label["top"] +
        label["bottom"]
    ) / 2

    label_height = max(
        label.get("height", 20),
        10
    )

    nearby = []

    for word in words:

        # 자기 자신은 제외
        if (
            word["left"] == label["left"]
            and
            word["top"] == label["top"]
        ):
            continue

        word_center_y = (
            word["top"] +
            word["bottom"]
        ) / 2

        vertical_distance = abs(
            word_center_y -
            label_center_y
        )

        # 같은 행 또는 인접 행
        if vertical_distance <= label_height * 2.8:

            nearby.append(word)

    # 왼쪽 → 오른쪽
    nearby.sort(
        key=lambda x: (
            abs(
                (
                    x["top"] +
                    x["bottom"]
                ) / 2
                -
                label_center_y
            ),
            x["left"]
        )
    )

    return nearby


# ============================================================
# 라벨 오른쪽 후보
# ============================================================

def right_side_candidates(
    words,
    label
):

    nearby = words_near_label(
        words,
        label
    )

    result = []

    label_right = label["right"]

    label_center_y = (
        label["top"] +
        label["bottom"]
    ) / 2

    for word in nearby:

        center_y = (
            word["top"] +
            word["bottom"]
        ) / 2

        # 라벨 오른쪽
        if word["left"] >= label_right - 5:

            vertical_distance = abs(
                center_y -
                label_center_y
            )

            result.append({
                "word": word,
                "distance": vertical_distance
            })

    result.sort(
        key=lambda x: (
            x["distance"],
            x["word"]["left"]
        )
    )

    return [
        x["word"]
        for x in result
    ]


# ============================================================
# 날짜 추출
# ============================================================

def normalize_date(text):

    if not text:
        return ""

    text = text.upper()

    # OCR 오인식 보정
    text = text.replace("O", "0")
    text = text.replace("I", "1")
    text = text.replace("L", "1")

    patterns = [

        # 2025-04-16
        r"(20\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})",

        # 2025 04 16
        r"(20\d{2})\s+(\d{2})\s+(\d{2})",

        # 20250416
        r"(20\d{2})(\d{2})(\d{2})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            yyyy = match.group(1)
            mm = match.group(2).zfill(2)
            dd = match.group(3).zfill(2)

            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:

                return (
                    f"{yyyy}"
                    f"{mm}"
                    f"{dd}"
                )

    return ""


# ============================================================
# 수주번호 추출
# ============================================================

def normalize_order(text):

    if not text:
        return ""

    text = text.upper()

    # 공백 제거
    text = re.sub(
        r"\s+",
        "",
        text
    )

    # OCR 문자 보정
    text = text.replace("—", "-")
    text = text.replace("–", "-")
    text = text.replace("_", "-")

    patterns = [

        # H250208UD-1
        r"H\d{6}[A-Z]{2}-\d+",

        # H260620UE
        r"H\d{6}[A-Z]{2}",

        # 조금 느슨한 형태
        r"H\d{6}[A-Z0-9\-]{2,}",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(0)

    return ""


# ============================================================
# PO 번호 추출
# ============================================================

def normalize_po(text):

    if not text:
        return ""

    text = text.upper()

    text = re.sub(
        r"\s+",
        "",
        text
    )

    # PO가 P0로 인식되는 경우를 고려
    patterns = [

        r"PO\d{8,}",

        r"P\d{8,}",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            value = match.group(0)

            # P02504050001 같은 실제 P+숫자 형식
            if re.fullmatch(
                r"P\d{8,}",
                value
            ):
                return value

            # PO02504050001 → P02504050001
            if value.startswith("PO"):

                return (
                    "P" +
                    value[2:]
                )

    return ""


# ============================================================
# 업체명 추출
# ============================================================

def normalize_vendor(text):

    if not text:
        return ""

    compact = compact_text(text)

    # --------------------------------------------------------
    # 1순위: 알려진 업체명
    # --------------------------------------------------------

    for vendor in KNOWN_VENDORS:

        if compact.find(
            compact_text(vendor)
        ) >= 0:

            return vendor


    # --------------------------------------------------------
    # 2순위: 일반적인 한글 업체명
    # --------------------------------------------------------

    text = re.sub(
        r"\(.*?\)",
        " ",
        text
    )

    candidates = re.findall(
        r"[가-힣]{2,}",
        text
    )

    exclude = {

        "업체",
        "소재지",
        "업체소재지",
        "주소",
        "경상남도",
        "경상북도",
        "경기도",
        "충청남도",
        "충청북도",
        "전라남도",
        "전라북도",
        "강원도",
        "서울",
        "부산",
        "대구",
        "인천",
        "광주",
        "대전",
        "울산",
        "세종",
        "창원시",
        "김해시",
        "천안시",
        "부산광역시",
        "경상남도창원시",
    }

    for candidate in candidates:

        if candidate not in exclude:

            if len(candidate) >= 2:

                return candidate

    return ""


# ============================================================
# 라벨 기반 필드 추출
# ============================================================

def extract_by_labels(words):

    result = {
        "order_no": "",
        "date": "",
        "vendor": "",
        "po_no": "",
    }

    # --------------------------------------------------------
    # 수주번호
    # --------------------------------------------------------

    order_label = find_label(
        words,
        [
            "수주번호",
            "Order No",
            "OrderNo",
            "Order"
        ]
    )

    if order_label:

        candidates = right_side_candidates(
            words,
            order_label
        )

        # 가까운 단어들을 조합
        candidate_text = " ".join(
            w["text"]
            for w in candidates[:8]
        )

        result["order_no"] = normalize_order(
            candidate_text
        )


    # --------------------------------------------------------
    # 의뢰일자
    # --------------------------------------------------------

    date_label = find_label(
        words,
        [
            "의뢰일자",
            "Issue Date",
            "IssueDate"
        ]
    )

    if date_label:

        candidates = right_side_candidates(
            words,
            date_label
        )

        candidate_text = " ".join(
            w["text"]
            for w in candidates[:10]
        )

        result["date"] = normalize_date(
            candidate_text
        )


    # --------------------------------------------------------
    # 발주서번호
    # --------------------------------------------------------

    po_label = find_label(
        words,
        [
            "발주서번호",
            "발주서 번호",
            "PO No",
            "PONo",
            "PO"
        ]
    )

    if po_label:

        candidates = right_side_candidates(
            words,
            po_label
        )

        candidate_text = " ".join(
            w["text"]
            for w in candidates[:10]
        )

        result["po_no"] = normalize_po(
            candidate_text
        )


    # --------------------------------------------------------
    # 업체명
    # --------------------------------------------------------

    vendor_label = find_label(
        words,
        [
            "업체소재지",
            "업체 소재지",
            "Vendor Address",
            "VendorAddress"
        ]
    )

    if vendor_label:

        candidates = right_side_candidates(
            words,
            vendor_label
        )

        candidate_text = " ".join(
            w["text"]
            for w in candidates[:12]
        )

        result["vendor"] = normalize_vendor(
            candidate_text
        )


    return result


# ============================================================
# 전체 OCR 텍스트 기반 보완
# ============================================================

def extract_by_regex(text):

    result = {
        "order_no": "",
        "date": "",
        "vendor": "",
        "po_no": "",
    }

    if not text:
        return result


    # --------------------------------------------------------
    # 수주번호
    # --------------------------------------------------------

    result["order_no"] = normalize_order(
        text
    )


    # --------------------------------------------------------
    # 날짜
    # --------------------------------------------------------

    date_patterns = [

        r"Issue\s*Date.{0,100}",
        r"의뢰일자.{0,100}",
    ]

    for pattern in date_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE |
            re.DOTALL
        )

        if match:

            value = normalize_date(
                match.group(0)
            )

            if value:

                result["date"] = value
                break


    if not result["date"]:

        result["date"] = normalize_date(
            text
        )


    # --------------------------------------------------------
    # PO
    # --------------------------------------------------------

    result["po_no"] = normalize_po(
        text
    )


    # --------------------------------------------------------
    # 업체명
    # --------------------------------------------------------

    result["vendor"] = normalize_vendor(
        text
    )


    return result


# ============================================================
# 결과 합치기
# ============================================================

def merge_results(results):

    final = {
        "order_no": "",
        "date": "",
        "vendor": "",
        "po_no": "",
    }

    # 우선순위:
    # 라벨 기반 → 전체 OCR
    for result in results:

        for key in final:

            if not final[key]:

                value = result.get(
                    key,
                    ""
                )

                if value:

                    final[key] = value

    return final


# ============================================================
# PDF 처리
# ============================================================

def convert_pdf(pdf_bytes):

    from pdf2image import convert_from_bytes

    return convert_from_bytes(
        pdf_bytes,
        dpi=300,
        fmt="png"
    )


# ============================================================
# 파일 업로드
# ============================================================

uploaded_file = st.file_uploader(
    "파일을 업로드하세요 (PDF, JPG, PNG)",
    type=[
        "pdf",
        "png",
        "jpg",
        "jpeg"
    ]
)


if uploaded_file is not None:

    try:

        # ====================================================
        # PDF
        # ====================================================

        if uploaded_file.type == "application/pdf":

            pdf_bytes = uploaded_file.read()

            with st.spinner(
                "PDF를 고해상도 이미지로 변환하는 중입니다..."
            ):

                pages = convert_pdf(
                    pdf_bytes
                )

            if not pages:

                st.error(
                    "PDF 페이지를 읽지 못했습니다."
                )

                st.stop()

            # 첫 페이지
            image = pages[0]

            if len(pages) > 1:

                st.info(
                    f"총 {len(pages)}페이지입니다. "
                    "현재는 첫 번째 페이지에서 필요한 정보를 찾습니다."
                )

        # ====================================================
        # 이미지
        # ====================================================

        else:

            image = Image.open(
                uploaded_file
            ).convert("RGB")


        # ====================================================
        # 원본 미리보기
        # ====================================================

        st.image(
            image,
            caption="업로드된 문서",
            use_container_width=True
        )


        # ====================================================
        # OCR 이미지 생성
        # ====================================================

        with st.spinner(
            "스캔본을 여러 방식으로 OCR 분석 중입니다..."
        ):

            ocr_images = make_ocr_images(
                image
            )


        all_results = []
        all_words = []
        all_texts = []


        # ====================================================
        # 여러 전처리 이미지 OCR
        # ====================================================

        for index, ocr_image in enumerate(
            ocr_images
        ):

            # OCR 단어 + 위치
            words = get_ocr_data(
                ocr_image,
                psm=6
            )

            if words:

                all_words.extend(
                    words
                )

                label_result = extract_by_labels(
                    words
                )

                all_results.append(
                    label_result
                )


            # 전체 텍스트
            text = get_ocr_text(
                ocr_image
            )

            if text:

                all_texts.append(
                    text
                )

                regex_result = extract_by_regex(
                    text
                )

                all_results.append(
                    regex_result
                )


        # ====================================================
        # 전체 OCR 텍스트 하나로 합치기
        # ====================================================

        full_text = "\n".join(
            all_texts
        )


        # ====================================================
        # 결과 합치기
        # ====================================================

        result = merge_results(
            all_results
        )


        # ====================================================
        # 알려진 업체명 최종 확인
        # ====================================================

        if not result["vendor"]:

            for vendor in KNOWN_VENDORS:

                if vendor in full_text:

                    result["vendor"] = vendor

                    break


        # ====================================================
        # 결과 표시
        # ====================================================

        st.success(
            "분석 완료!"
        )

        st.markdown(
            "### 📊 추출된 항목 확인 및 수정"
        )


        col1, col2 = st.columns(2)


        with col1:

            final_order = st.text_input(
                "수주번호",
                value=result["order_no"]
            )

            final_date = st.text_input(
                "의뢰일자",
                value=result["date"],
                placeholder="예: 20250416"
            )


        with col2:

            final_vendor = st.text_input(
                "업체명",
                value=result["vendor"]
            )

            final_po = st.text_input(
                "발주서번호",
                value=result["po_no"]
            )


        # ====================================================
        # 최종 파일명
        # ====================================================

        result_filename = (
            f"{final_order}_"
            f"{final_date}_"
            f"{final_vendor}_"
            f"{final_po}"
        )


        st.markdown("---")

        st.markdown(
            "### ✨ 최종 파일명"
        )

        st.code(
            result_filename,
            language=""
        )


        # ====================================================
        # 복사 버튼
        # ====================================================

        copy_html = f"""
        <button
            onclick="navigator.clipboard.writeText('{result_filename}')"
            style="
                width:100%;
                padding:12px;
                font-size:16px;
                border:none;
                border-radius:8px;
                cursor:pointer;
            ">
            📋 파일명 복사
        </button>
        """

        st.components.v1.html(
            copy_html,
            height=55
        )


        # ====================================================
        # 인식 상태
        # ====================================================

        st.markdown(
            "### 🔎 인식 상태"
        )

        status = [
            ("수주번호", final_order),
            ("의뢰일자", final_date),
            ("업체명", final_vendor),
            ("발주서번호", final_po),
        ]


        for label, value in status:

            if value:

                st.success(
                    f"✓ {label}: {value}"
                )

            else:

                st.warning(
                    f"⚠ {label}: 인식되지 않았습니다."
                )


        # ====================================================
        # OCR 원문
        # ====================================================

        with st.expander(
            "🔍 OCR 원문 보기"
        ):

            st.text(
                full_text
            )


        # ====================================================
        # OCR 단어 위치 디버깅
        # ====================================================

        with st.expander(
            "🛠 OCR이 실제로 읽은 단어 보기"
        ):

            if all_words:

                # 중복 제거
                seen = set()
                display_words = []

                for word in all_words:

                    key = (
                        word["text"],
                        word["left"],
                        word["top"]
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    display_words.append(
                        word
                    )

                display_words.sort(
                    key=lambda x: (
                        x["top"],
                        x["left"]
                    )
                )

                for word in display_words[:300]:

                    st.write(
                        f'{word["text"]} '
                        f'(신뢰도 {word["conf"]:.0f})'
                    )

            else:

                st.write(
                    "OCR 단어를 찾지 못했습니다."
                )


    except Exception as e:

        st.error(
            f"파일 처리 중 오류가 발생했습니다: {e}"
        )

        st.exception(e)
