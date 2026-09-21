import streamlit as st
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import re
import os
import io

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
    "스캔된 PDF 또는 이미지에서 수주번호, 의뢰일자, 업체명, 발주서번호를 추출합니다."
)

st.markdown("---")


# ============================================================
# OCR 전처리
# ============================================================

def preprocess_image(image, scale=3, threshold=False):
    """
    OCR 인식률을 높이기 위한 이미지 전처리
    """

    image = image.convert("L")

    # 확대
    w, h = image.size
    image = image.resize(
        (w * scale, h * scale),
        Image.Resampling.LANCZOS
    )

    # 대비 향상
    image = ImageOps.autocontrast(image)

    # 선명하게
    image = image.filter(ImageFilter.SHARPEN)

    image = ImageEnhance.Contrast(image).enhance(1.5)

    # 필요할 경우 흑백화
    if threshold:
        image = image.point(
            lambda p: 255 if p > 170 else 0
        )

    return image


# ============================================================
# OCR 실행
# ============================================================

def run_ocr(image, lang="kor+eng", psm=6, whitelist=None):
    """
    여러 조건에서 OCR 실행
    """

    config = f"--oem 3 --psm {psm}"

    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"

    try:
        return pytesseract.image_to_string(
            image,
            lang=lang,
            config=config
        )
    except Exception:
        return ""


# ============================================================
# 문자열 정리
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\x0c", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# 수주번호 정리
# 예:
# H250208UD-1
# H260620UE
# ============================================================

def normalize_order_no(text):

    if not text:
        return ""

    text = text.upper()
    text = text.replace(" ", "")
    text = text.replace("_", "-")

    # OCR에서 자주 발생하는 혼동
    text = text.replace("—", "-")
    text = text.replace("–", "-")

    # H + 6자리 + 영문2자리 + 선택적 -숫자
    match = re.search(
        r"H\d{6}[A-Z]{2}(?:-\d+)?",
        text
    )

    if match:
        return match.group(0)

    # 혹시 숫자/문자가 붙어 있는 경우
    match = re.search(
        r"H\d{6}[A-Z0-9\-]{2,}",
        text
    )

    if match:
        return match.group(0)

    return ""


# ============================================================
# 날짜 정리
# ============================================================

def normalize_date(text):

    if not text:
        return ""

    # OCR에서 흔한 문자 제거
    text = text.replace(" ", "")

    # 2025-04-16
    match = re.search(
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})",
        text
    )

    if match:
        yyyy = match.group(1)
        mm = match.group(2).zfill(2)
        dd = match.group(3).zfill(2)

        return f"{yyyy}{mm}{dd}"

    # 2025 04 16
    match = re.search(
        r"(20\d{2})(\d{2})(\d{2})",
        text
    )

    if match:
        return "".join(match.groups())

    return ""


# ============================================================
# PO 번호 정리
# 예:
# P02504050001
# ============================================================

def normalize_po_no(text):

    if not text:
        return ""

    text = text.upper()
    text = text.replace(" ", "")
    text = text.replace("-", "")

    # PO가 OCR에서 P0로 읽히는 경우
    # 실제 양식은 P + 숫자 형태이므로 P로 시작하는 숫자 검색
    match = re.search(
        r"P\d{8,}",
        text
    )

    if match:
        return match.group(0)

    # OCR이 PO라고 읽은 경우
    match = re.search(
        r"PO\d{8,}",
        text
    )

    if match:
        value = match.group(0)

        # 이 양식의 PO 번호가 P + 숫자라면
        # PO가 아니라 P로 정리
        if len(value) > 2:
            return "P" + value[2:]

        return value

    return ""


# ============================================================
# 업체명 정리
# ============================================================

KNOWN_VENDORS = [
    "신진볼텍",
    "동남볼트",
    "일신피티에프이",
    "에스엔피머티리얼",
]


def normalize_vendor(text):

    if not text:
        return ""

    text = clean_text(text)

    # 괄호/주소 제거
    text = re.sub(
        r"\(.*?\)",
        "",
        text
    )

    # 먼저 등록된 업체명과 정확/부분 매칭
    for company in KNOWN_VENDORS:

        if company in text:
            return company

        # OCR 공백 때문에 분리된 경우
        compact = text.replace(" ", "")

        if company in compact:
            return company

    # 한글 업체명 추출
    korean_matches = re.findall(
        r"[가-힣]{2,}",
        text
    )

    # 주소 단어 제거
    address_words = [
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
        "천안시",
        "김해시",
        "주소",
        "업체소재지",
        "업체",
        "소재지",
    ]

    for word in korean_matches:

        if word in address_words:
            continue

        if len(word) >= 2:
            return word

    return ""


# ============================================================
# 실제 양식의 지정 영역 OCR
# ============================================================

def crop_ratio(image, x1, y1, x2, y2):
    """
    이미지 크기에 관계없이 비율로 영역을 잘라냄
    """

    w, h = image.size

    return image.crop(
        (
            int(w * x1),
            int(h * y1),
            int(w * x2),
            int(h * y2)
        )
    )


def extract_from_fixed_regions(image):

    result = {
        "order_no": "",
        "date": "",
        "vendor": "",
        "po_no": ""
    }

    # --------------------------------------------------------
    # 현재 올려주신 실제 양식 기준 위치
    #
    # 업체명:
    # 상단 Vendor Address 오른쪽
    #
    # 의뢰일자:
    # Issue Date 오른쪽
    #
    # 수주번호:
    # Order No 오른쪽
    #
    # PO:
    # PO No 오른쪽
    # --------------------------------------------------------

    regions = {

        # 업체명
        "vendor": crop_ratio(
            image,
            0.335, 0.025,
            0.475, 0.095
        ),

        # 수주번호
        "order_no": crop_ratio(
            image,
            0.335, 0.145,
            0.475, 0.215
        ),

        # 의뢰일자
        "date": crop_ratio(
            image,
            0.225, 0.195,
            0.355, 0.255
        ),

        # PO 번호
        "po_no": crop_ratio(
            image,
            0.775, 0.195,
            0.915, 0.255
        )
    }

    # --------------------------------------------------------
    # 업체명 OCR
    # --------------------------------------------------------

    vendor_img = preprocess_image(
        regions["vendor"],
        scale=4,
        threshold=False
    )

    vendor_text_1 = run_ocr(
        vendor_img,
        lang="kor+eng",
        psm=7
    )

    vendor_img_bw = preprocess_image(
        regions["vendor"],
        scale=4,
        threshold=True
    )

    vendor_text_2 = run_ocr(
        vendor_img_bw,
        lang="kor+eng",
        psm=7
    )

    vendor_text = vendor_text_1 + " " + vendor_text_2

    result["vendor"] = normalize_vendor(vendor_text)

    # --------------------------------------------------------
    # 수주번호 OCR
    # --------------------------------------------------------

    order_img = preprocess_image(
        regions["order_no"],
        scale=4,
        threshold=False
    )

    order_text = run_ocr(
        order_img,
        lang="eng",
        psm=7,
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
    )

    result["order_no"] = normalize_order_no(order_text)

    # --------------------------------------------------------
    # 날짜 OCR
    # --------------------------------------------------------

    date_img = preprocess_image(
        regions["date"],
        scale=4,
        threshold=False
    )

    date_text = run_ocr(
        date_img,
        lang="eng",
        psm=7,
        whitelist="0123456789-./"
    )

    result["date"] = normalize_date(date_text)

    # --------------------------------------------------------
    # PO 번호 OCR
    # --------------------------------------------------------

    po_img = preprocess_image(
        regions["po_no"],
        scale=4,
        threshold=False
    )

    po_text = run_ocr(
        po_img,
        lang="eng",
        psm=7,
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    )

    result["po_no"] = normalize_po_no(po_text)

    return result, regions


# ============================================================
# 전체 페이지 OCR
# 지정 영역 OCR이 실패했을 경우 보완
# ============================================================

def extract_from_full_ocr(image):

    result = {
        "order_no": "",
        "date": "",
        "vendor": "",
        "po_no": ""
    }

    processed = preprocess_image(
        image,
        scale=2,
        threshold=False
    )

    text1 = run_ocr(
        processed,
        lang="kor+eng",
        psm=6
    )

    processed_bw = preprocess_image(
        image,
        scale=2,
        threshold=True
    )

    text2 = run_ocr(
        processed_bw,
        lang="kor+eng",
        psm=6
    )

    text = text1 + "\n" + text2

    # --------------------------------------------------------
    # 수주번호
    # --------------------------------------------------------

    result["order_no"] = normalize_order_no(text)

    # --------------------------------------------------------
    # 날짜
    # --------------------------------------------------------

    # Issue Date / 의뢰일자 주변
    date_patterns = [
        r"Issue\s*Date.{0,100}?(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
        r"의뢰일자.{0,100}?(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
        r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
    ]

    for pattern in date_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:
            result["date"] = normalize_date(
                match.group(1)
            )
            break

    # --------------------------------------------------------
    # 업체명
    # --------------------------------------------------------

    result["vendor"] = normalize_vendor(text)

    # --------------------------------------------------------
    # PO
    # --------------------------------------------------------

    po_patterns = [
        r"PO\s*No\.?.{0,80}?([Pp]?\d{8,})",
        r"발주서\s*번호.{0,80}?([Pp]?\d{8,})",
        r"\b(P\d{8,})\b",
    ]

    for pattern in po_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:
            result["po_no"] = normalize_po_no(
                match.group(1)
            )
            break

    return result, text


# ============================================================
# PDF → 이미지
# ============================================================

def pdf_to_images(pdf_bytes):

    from pdf2image import convert_from_bytes

    images = convert_from_bytes(
        pdf_bytes,
        dpi=300,
        fmt="png"
    )

    return images


# ============================================================
# 파일 업로드
# ============================================================

uploaded_file = st.file_uploader(
    "파일을 업로드하세요 (PDF, JPG, PNG)",
    type=["pdf", "png", "jpg", "jpeg"]
)


if uploaded_file is not None:

    try:

        # ====================================================
        # PDF 처리
        # ====================================================

        if uploaded_file.type == "application/pdf":

            pdf_bytes = uploaded_file.read()

            with st.spinner("PDF를 이미지로 변환하는 중입니다..."):
                images = pdf_to_images(pdf_bytes)

            if not images:
                st.error("PDF에서 이미지를 불러오지 못했습니다.")
                st.stop()

            # 현재 양식은 1페이지 기준
            image = images[0]

            if len(images) > 1:
                st.info(
                    f"총 {len(images)}페이지가 확인되었습니다. "
                    "현재는 첫 번째 페이지를 기준으로 분석합니다."
                )

        # ====================================================
        # 이미지 처리
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
            caption="업로드된 문서 미리보기",
            use_container_width=True
        )


        # ====================================================
        # OCR 분석
        # ====================================================

        with st.spinner(
            "문서를 정밀 분석 중입니다..."
        ):

            # 1차: 실제 양식의 고정 영역 OCR
            fixed_result, regions = extract_from_fixed_regions(
                image
            )

            # 2차: 전체 OCR
            full_result, full_text = extract_from_full_ocr(
                image
            )

            # =================================================
            # 결과 합치기
            #
            # 고정영역 OCR 결과를 우선
            # 실패한 항목만 전체 OCR 결과 사용
            # =================================================

            order_no = (
                fixed_result["order_no"]
                or full_result["order_no"]
            )

            date = (
                fixed_result["date"]
                or full_result["date"]
            )

            vendor = (
                fixed_result["vendor"]
                or full_result["vendor"]
            )

            po_no = (
                fixed_result["po_no"]
                or full_result["po_no"]
            )


        # ====================================================
        # 샘플 양식에서 업체명이 OCR 실패할 경우
        # 전체 OCR에 회사명이 존재하는지 한번 더 확인
        # ====================================================

        if not vendor:

            for company in KNOWN_VENDORS:

                if company in full_text:

                    vendor = company
                    break


        # ====================================================
        # 분석 완료
        # ====================================================

        st.success("분석 완료!")


        # ====================================================
        # 추출 결과
        # ====================================================

        st.markdown(
            "### 📊 추출된 항목 확인 및 수정"
        )

        col1, col2 = st.columns(2)

        with col1:

            final_order = st.text_input(
                "수주번호",
                value=order_no
            )

            final_date = st.text_input(
                "의뢰일자",
                value=date,
                placeholder="예: 20250416"
            )

        with col2:

            final_vendor = st.text_input(
                "업체명",
                value=vendor,
                placeholder="예: 신진볼텍"
            )

            final_po = st.text_input(
                "발주서번호",
                value=po_no,
                placeholder="예: P02504050001"
            )


        # ====================================================
        # 파일명 생성
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
        # 추출 상태 표시
        # ====================================================

        st.markdown("### 🔎 인식 상태")

        status_data = [
            ("수주번호", final_order),
            ("의뢰일자", final_date),
            ("업체명", final_vendor),
            ("발주서번호", final_po),
        ]

        for label, value in status_data:

            if value:

                st.success(
                    f"✓ {label}: {value}"
                )

            else:

                st.warning(
                    f"⚠ {label}: 인식되지 않았습니다."
                )


        # ====================================================
        # OCR 원문 보기
        # ====================================================

        with st.expander(
            "🔍 OCR 원문 보기"
        ):

            st.text(
                full_text
            )


        # ====================================================
        # OCR 영역 확인
        # 디버깅용
        # ====================================================

        with st.expander(
            "🛠 OCR 인식 영역 확인"
        ):

            st.write(
                "현재 발주서 양식에서 다음 영역을 별도로 확대하여 OCR합니다."
            )

            st.image(
                regions["vendor"],
                caption="업체명 인식 영역",
                use_container_width=True
            )

            st.image(
                regions["order_no"],
                caption="수주번호 인식 영역",
                use_container_width=True
            )

            st.image(
                regions["date"],
                caption="의뢰일자 인식 영역",
                use_container_width=True
            )

            st.image(
                regions["po_no"],
                caption="발주서번호 인식 영역",
                use_container_width=True
            )


    except Exception as e:

        st.error(
            f"파일 처리 중 오류가 발생했습니다: {e}"
        )

        st.exception(e)
