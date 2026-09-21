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
# 🔧 헬퍼 함수
# ============================================================
def is_address_like(text: str) -> bool:
    """주소로 보이는 텍스트 판별"""
    if re.fullmatch(r'[\d\s\-().]+', text):
        return True
    if any(k in text for k in ['광역시', '특별시', '특별자치', '번길', '사우', '층']):
        return True
    if re.search(r'(시|도|구|군|동|읍|면|로|길|번길|호|층)$', text):
        return True
    return False


def extract_vendor_name(data_df: pd.DataFrame, full_text: str) -> str:
    """
    '업체소재지' 앵커의 우측 값 셀에서 상호명만 정밀 추출
    - 라벨 셀에 포함된 'Vendor', 'Address' 영어 라벨을 완전 차단
    - 앵커와 같은 행(회사명 줄)의 토큰만 사용하여 주소 줄 배제
    """
    # 1) 앵커 찾기 (한글 우선, 없으면 영문)
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

    a_top, a_left = anchor['top'], anchor['left']
    a_width, a_height = anchor['width'], anchor['height']

    # 2) 라벨 셀의 '진짜 오른쪽 경계' 계산
    #    (업체소재지 + Vendor + Address 중 가장 오른쪽 끝)
    row_band = data_df[
        (data_df['top'] >= a_top - 5) &
        (data_df['top'] <= a_top + a_height + 35)
    ]
    label_mask = row_band['text'].str.contains(
        r'업체|소재지|Vendor|Address', na=False, case=False, regex=True
    )
    label_tokens = row_band[label_mask]
    if not label_tokens.empty:
        label_cell_right = (label_tokens['left'] + label_tokens['width']).max()
    else:
        label_cell_right = a_left + a_width

    # 3) 값 셀에서 '앵커와 같은 행'만 후보로 (주소 줄 완전 차단)
    value_tokens = data_df[
        (data_df['left'] > label_cell_right + 2) &
        (data_df['top'] >= a_top - 8) &
        (data_df['top'] <= a_top + a_height + 8) &
        (data_df['conf'] >= 15)
    ].copy()

    # 4) 영어 라벨 단어 완전 차단
    noise_re = re.compile(
        r'(vendor|address|inspected|reviewed|approved|by|order|customer|'
        r'deliver|item|material|remark|result)',
        re.IGNORECASE
    )
    value_tokens = value_tokens[
        ~value_tokens['text'].str.contains(noise_re, na=False, regex=True)
    ]

    if value_tokens.empty:
        m = re.search(
            r'([가-힣A-Za-z][가-힣A-Za-z0-9]{1,}'
            r'(?:머티리얼|테크|산업|정밀|소재|전자|화학|시스템|솔루션|상사|공업))',
            full_text
        )
        return m.group(1) if m else ""

    # 5) 같은 행 토큰 좌→우 병합
    value_tokens = value_tokens.sort_values(by='left')
    merged = ''.join(value_tokens['text'].str.strip().tolist())
    merged = re.sub(r'\s+', '', merged)
    merged = re.sub(r'[^가-힣a-zA-Z0-9()&.\-]', '', merged)

    # 6) 검증
    if (len(merged) >= 2
            and re.search(r'[가-힣a-zA-Z]', merged)
            and not is_address_like(merged)):
        return merged

    # 7) 폴백 정규식
    m = re.search(
        r'([가-힣A-Za-z][가-힣A-Za-z0-9]{1,}'
        r'(?:머티리얼|테크|산업|정밀|소재|전자|화학|시스템|솔루션|상사|공업))',
        full_text
    )
    return m.group(1) if m else ""


# ============================================================
# 메인 로직
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
                images = convert_from_bytes(uploaded_file.read())
                if images:
                    image = images[0]
            except Exception as pdf_err:
                st.error(f"PDF 변환 중 오류 발생: {pdf_err}")
        else:
            image = Image.open(uploaded_file)

        if image:
            st.image(image, caption="업로드된 문서 미리보기", use_container_width=True)

            with st.spinner("AI가 문서를 정밀 분석 중입니다..."):
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
                for m in date_matches:
                    digits = re.sub(r'[^0-9]', '', m)
                    if len(digits) == 8 and digits.startswith('20'):
                        date = digits
                        break

                if not date:
                    for _, r in data_df.iterrows():
                        digits = re.sub(r'[^0-9]', '', r['text'])
                        if len(digits) == 8 and digits.startswith('202'):
                            date = digits
                            break

                # ---------- 3. 업체명 ----------
                vendor = extract_vendor_name(data_df, full_text)
                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # ---------- 4. 발주서번호 ----------
                po_no = ""
                po_match = re.search(
                    r'(PO?[0-9]{8,})', full_text, re.IGNORECASE
                )
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

            # ---------- 디버깅용 (필요할 때만 체크) ----------
            if st.checkbox("🔍 OCR 좌표 디버깅 보기"):
                st.dataframe(
                    data_df[['text', 'left', 'top', 'width', 'height', 'conf']]
                    .sort_values(by=['top', 'left'])
                    .reset_index(drop=True)
                )

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
