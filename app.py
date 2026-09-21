import streamlit as st
import pytesseract
from PIL import Image
import pandas as pd
import re
import os

os.environ['PATH'] += os.pathsep + '/usr/bin'

st.set_page_config(page_title="인수검사서 파일명 자동 생성기", page_icon="📄", layout="centered")

st.title("📄 인수검사서 파일명 자동 생성기")
st.write("스캔된 PDF나 이미지 파일을 업로드하면 문서 표 구조를 분석하여 올바른 파일명을 만들어 줍니다.")
st.markdown("---")


# ============================================================
# 🔧 헬퍼
# ============================================================
def is_address_like(text: str) -> bool:
    if re.fullmatch(r'[\d\s\-().]+', text):
        return True
    if any(k in text for k in ['광역시', '특별시', '특별자치', '번길', '사우', '층']):
        return True
    if re.search(r'(시|도|구|군|동|읍|면|로|길|번길|호|층)$', text):
        return True
    return False


def clean_text(txt: str) -> str:
    txt = re.sub(r'\s+', '', txt)
    txt = re.sub(r'[^가-힣a-zA-Z0-9()&.\-]', '', txt)
    return txt


def ocr_cell(cropped: Image.Image) -> str:
    """
    잘라낸 셀 이미지를 업스케일 + 이진화 후 한글 위주로 OCR
    여러 PSM/lang 조합을 시도해서 가장 그럴듯한 결과 반환
    """
    # 업스케일 4배
    w, h = cropped.size
    if w < 20 or h < 10:
        return ""
    img = cropped.convert('L').resize((w * 4, h * 4), Image.LANCZOS)

    # 이진화 (배경 흰색, 글자 검정)
    img = img.point(lambda x: 0 if x < 150 else 255, '1')

    candidates = []
    # lang별, psm별 시도
    for lang in ['kor', 'kor+eng']:
        for psm in [7, 6, 8, 13]:
            try:
                txt = pytesseract.image_to_string(
                    img, lang=lang, config=f'--psm {psm}'
                )
            except Exception:
                continue
            c = clean_text(txt)
            if len(c) < 2:
                continue
            if is_address_like(c):
                continue
            if not re.search(r'[가-힣]', c):
                continue
            kor_cnt = sum(1 for ch in c if '가' <= ch <= '힣')
            candidates.append((c, kor_cnt, lang, psm))

    if not candidates:
        return ""

    # 한글 글자수 많은 순 → 길이 순
    candidates.sort(key=lambda x: (-x[1], -len(x[0])))
    return candidates[0][0]


def extract_vendor_name(image: Image.Image,
                        data_df: pd.DataFrame,
                        full_text: str) -> str:
    # ---------- 1) 앵커 찾기 ----------
    kor_anchors = data_df[data_df['text'].str.contains('업체|소재지', na=False)]
    if not kor_anchors.empty:
        anchor = kor_anchors.sort_values(
            by=['top', 'conf'], ascending=[True, False]
        ).iloc[0]
    else:
        eng = data_df[data_df['text'].str.contains('Vendor', na=False, case=False)]
        if eng.empty:
            return ""
        anchor = eng.sort_values(by='top').iloc[0]

    a_top = int(anchor['top'])
    a_left = int(anchor['left'])
    a_width = int(anchor['width'])
    a_height = int(anchor['height'])

    # ---------- 2) 라벨 셀 오른쪽 경계 ----------
    row_band = data_df[
        (data_df['top'] >= a_top - 5) &
        (data_df['top'] <= a_top + a_height + 35)
    ]
    label_tokens = row_band[row_band['text'].str.contains(
        r'업체|소재지|Vendor|Address', na=False, case=False, regex=True
    )]
    if not label_tokens.empty:
        label_right = int(
            (label_tokens['left'] + label_tokens['width']).max()
        )
    else:
        label_right = a_left + a_width

    # ---------- 3) 값 셀(회사명 줄)만 크롭 ----------
    #   y: 앵커 top 부근 (회사명이 있는 줄)
    #   x: 라벨 오른쪽 ~ 충분히 오른쪽
    cell_x1 = max(0, label_right + 2)
    cell_x2 = min(image.width, label_right + 420)
    cell_y1 = max(0, a_top - 6)
    cell_y2 = min(image.height, a_top + a_height + 8)

    # 너무 좁으면 앵커 세로 길이의 1.5배로 확장
    if cell_y2 - cell_y1 < 10:
        cell_y2 = cell_y1 + max(20, int(a_height * 1.5))

    cropped = image.crop((cell_x1, cell_y1, cell_x2, cell_y2))

    # ---------- 4) 크롭 셀 정밀 OCR ----------
    vendor = ocr_cell(cropped)

    # ---------- 5) 검증 ----------
    if vendor and len(vendor) >= 2 and not is_address_like(vendor):
        return vendor

    # ---------- 6) 폴백 1: 앵커 위쪽 값 셀에서 한 번 더 시도 ----------
    #   (라벨과 값의 baseline이 어긋난 경우 대비)
    for dy in (-10, -20, +10):
        y1 = max(0, cell_y1 + dy)
        y2 = min(image.height, cell_y2 + dy)
        cropped2 = image.crop((cell_x1, y1, cell_x2, y2))
        v2 = ocr_cell(cropped2)
        if v2 and len(v2) >= 2 and not is_address_like(v2):
            return v2

    # ---------- 7) 폴백 2: 전체 텍스트 정규식 ----------
    m = re.search(
        r'([가-힣A-Za-z][가-힣A-Za-z0-9]{1,}'
        r'(?:머티리얼|테크|산업|정밀|소재|전자|화학|시스템|솔루션|상사|공업|'
        r'㈜|\(주\)|주식회사))',
        full_text
    )
    if m:
        return clean_text(m.group(1))

    return ""


# ============================================================
# 메인
# ============================================================
uploaded_file = st.file_uploader(
    "파일을 업로드하세요 (PDF, JPG, PNG)",
    type=["pdf", "png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    try:
        image = None
        if uploaded_file.type == "application/pdf":
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(uploaded_file.read(), dpi=300)
                if images:
                    image = images[0]
            except Exception as pdf_err:
                st.error(f"PDF 변환 중 오류 발생: {pdf_err}")
        else:
            image = Image.open(uploaded_file)

        if image:
            st.image(image, caption="업로드된 문서 미리보기", use_container_width=True)

            with st.spinner("AI가 문서를 정밀 분석 중입니다..."):
                # 좌표 획득용 OCR (원본 해상도)
                full_text = pytesseract.image_to_string(image, lang='kor+eng')
                data_df = pytesseract.image_to_data(
                    image,
                    output_type=pytesseract.Output.DATAFRAME,
                    lang='kor+eng',
                    config='--psm 6'
                )
                data_df = data_df[
                    data_df.text.notnull() & (data_df.text.str.strip() != '')
                ].copy()
                data_df['conf'] = pd.to_numeric(
                    data_df['conf'], errors='coerce'
                ).fillna(0)

                # ---------- 1. 수주번호 ----------
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', full_text)
                if order_match:
                    order_no = re.sub(
                        r'[^A-Za-z0-9\-]', '', order_match.group(1).strip()
                    )
                else:
                    alt = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', full_text)
                    if alt:
                        order_no = alt.group(1).strip()

                # ---------- 2. 의뢰일자 ----------
                date = ""
                date_matches = re.findall(
                    r'(20[2-9][0-9][-/.][0-9]{2}[-/.][0-9]{2})', full_text
                )
                for mm in date_matches:
                    digits = re.sub(r'[^0-9]', '', mm)
                    if len(digits) == 8 and digits.startswith('20'):
                        date = digits
                        break
                if not date:
                    for _, r in data_df.iterrows():
                        digits = re.sub(r'[^0-9]', '', r['text'])
                        if len(digits) == 8 and digits.startswith('202'):
                            date = digits
                            break

                # ---------- 3. 업체명 (셀 크롭 + 정밀 OCR) ----------
                vendor = extract_vendor_name(image, data_df, full_text)
                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # ---------- 4. 발주서번호 ----------
                po_no = ""
                po_match = re.search(r'(PO?[0-9]{8,})', full_text, re.IGNORECASE)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    alt_po = re.search(
                        r'발주서[^\w]*번호[^\w]*([A-Za-z0-9]+)', full_text
                    )
                    if alt_po:
                        po_no = alt_po.group(1).strip()

            st.success("분석 완료!")

            st.markdown("### 📊 추출된 항목 확인 및 수정")
            col1, col2 = st.columns(2)
            with col1:
                final_order = st.text_input("수주번호", value=order_no)
                final_date = st.text_input("의뢰일자", value=date)
            with col2:
                final_vendor = st.text_input("업체명", value=vendor)
                final_po = st.text_input("발주서번호", value=po_no)

            result_filename = f"{final_order}_{final_date}_{final_vendor}_{final_po}"

            st.markdown("---")
            st.markdown("### ✨ 최종 파일명")
            st.code(result_filename, language="")

            st.info("💡 위 파일명을 복사해서 사내 파일명 변경에 사용하세요!")

            # ---------- 디버깅 ----------
            with st.expander("🔍 OCR 좌표 디버깅 / 크롭 이미지 보기"):
                st.dataframe(
                    data_df[['text', 'left', 'top', 'width', 'height', 'conf']]
                    .sort_values(by=['top', 'left'])
                    .reset_index(drop=True)
                )
                # 크롭 결과 미리보기
                kor_anchors = data_df[data_df['text'].str.contains('업체|소재지', na=False)]
                if not kor_anchors.empty:
                    a = kor_anchors.sort_values(by=['top', 'conf'],
                                                ascending=[True, False]).iloc[0]
                    a_top = int(a['top']); a_left = int(a['left'])
                    a_width = int(a['width']); a_height = int(a['height'])
                    row_band = data_df[
                        (data_df['top'] >= a_top - 5) &
                        (data_df['top'] <= a_top + a_height + 35)
                    ]
                    lt = row_band[row_band['text'].str.contains(
                        r'업체|소재지|Vendor|Address', na=False, case=False, regex=True
                    )]
                    label_right = int((lt['left'] + lt['width']).max()) if not lt.empty else a_left + a_width
                    x1 = max(0, label_right + 2)
                    x2 = min(image.width, label_right + 420)
                    y1 = max(0, a_top - 6)
                    y2 = min(image.height, a_top + a_height + 8)
                    st.write(f"크롭 영역: x=({x1},{x2}), y=({y1},{y2})")
                    st.image(
                        image.crop((x1, y1, x2, y2)),
                        caption="업체명 셀 크롭 결과 (여기가 선명해야 함)",
                        use_container_width=True
                    )

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
