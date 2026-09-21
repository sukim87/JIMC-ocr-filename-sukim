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

uploaded_file = st.file_uploader("파일을 업로드하세요 (PDF, JPG, PNG)", type=["pdf", "png", "jpg", "jpeg"])

# ============================================================
# 🔧 헬퍼 함수들
# ============================================================
def is_address_like(text: str) -> bool:
    """주소로 보이는 텍스트인지 판별 (시/도/구/동/로/길/번길/호 등)"""
    # 순수 숫자/기호는 주소로 간주
    if re.fullmatch(r'[\d\s\-().]+', text):
        return True
    # 주소 키워드가 들어간 경우
    addr_keywords = ['광역시', '특별시', '특별자치', '번길', '로 ', '길 ', '동 ', '읍 ', '면 ']
    if any(k in text for k in addr_keywords):
        return True
    # 시/도/구/동/로/길/호 로 끝나는 경우
    if re.search(r'(시|도|구|군|동|읍|면|로|길|번길|호|층)$', text):
        return True
    return False


def is_company_like(text: str) -> bool:
    """상호명으로 보이는 텍스트인지 판별"""
    if len(text) < 2:
        return False
    # 한글/영문/숫자 조합이고, 주소 패턴이 아니어야 함
    if not re.search(r'[가-힣a-zA-Z]', text):
        return False
    if is_address_like(text):
        return False
    # 특수문자만 있는 경우 제외
    if re.fullmatch(r'[^\w가-힣]+', text):
        return False
    return True


def extract_vendor_name(data_df: pd.DataFrame, full_text: str) -> str:
    """
    '업체소재지' 앵커의 우측 셀에서 상호명만 정밀 추출
    - 결재란(좌측 세로쓰기)과 주소(2번째 줄)를 완전히 배제
    """
    # 1) 앵커 탐색: '업체소재지' 또는 'Vendor' 포함 토큰
    anchor_candidates = data_df[
        data_df['text'].str.contains('업체소재지|업체 소재지|Vendor', na=False, case=False)
    ]
    if anchor_candidates.empty:
        # 폴백: '업체' 포함 토큰 중 가장 신뢰도 높은 것
        anchor_candidates = data_df[
            data_df['text'].str.contains('업체', na=False)
        ].sort_values(by='conf', ascending=False)

    if anchor_candidates.empty:
        return ""

    anchor = anchor_candidates.iloc[0]
    a_top = anchor['top']
    a_left = anchor['left']
    a_width = anchor['width']
    a_height = anchor['height']

    # 2) 앵커 우측 셀 영역 설정
    #    - x: 앵커 오른쪽 끝 ~ +350px (셀 폭 고려)
    #    - y: 앵커 상단 -20 ~ +60px (상호명+주소 두 줄 커버)
    cell_x_min = a_left + a_width + 3
    cell_x_max = a_left + a_width + 350
    cell_y_min = a_top - 20
    cell_y_max = a_top + a_height + 60

    cell_tokens = data_df[
        (data_df['left'] >= cell_x_min) &
        (data_df['left'] <= cell_x_max) &
        (data_df['top'] >= cell_y_min) &
        (data_df['top'] <= cell_y_max) &
        (data_df['conf'] >= 20)  # 저신뢰도 노이즈 제거
    ].copy()

    if cell_tokens.empty:
        return ""

    # 3) y좌표 클러스터링으로 줄(line) 그룹화
    #    - top 값 기준으로 8px 이내면 같은 줄로 묶음
    cell_tokens = cell_tokens.sort_values(by=['top', 'left']).reset_index(drop=True)
    lines = []
    current_line = []
    prev_top = None

    for _, row in cell_tokens.iterrows():
        if prev_top is None or abs(row['top'] - prev_top) <= 8:
            current_line.append(row)
        else:
            lines.append(current_line)
            current_line = [row]
        prev_top = row['top']
    if current_line:
        lines.append(current_line)

    # 4) 각 줄을 문자열로 병합 + 주소 여부 판정
    line_texts = []
    for line in lines:
        # 같은 줄 내에서 left 기준 정렬 후 병합
        line_sorted = sorted(line, key=lambda r: r['left'])
        merged = ''.join(r['text'].strip() for r in line_sorted)
        merged = re.sub(r'\s+', '', merged)  # 공백 제거
        # 노이즈 문자 정리
        merged = re.sub(r'[^가-힣a-zA-Z0-9()&.\-]', '', merged)
        if merged:
            line_texts.append({
                'text': merged,
                'top': line_sorted[0]['top'],
                'is_addr': is_address_like(merged),
                'avg_conf': sum(r['conf'] for r in line_sorted) / len(line_sorted),
            })

    if not line_texts:
        return ""

    # 5) 상호명 후보 선정
    #    (1순위) 주소가 아닌 줄 중 최상단
    non_addr_lines = [l for l in line_texts if not l['is_addr'] and is_company_like(l['text'])]
    if non_addr_lines:
        non_addr_lines.sort(key=lambda x: x['top'])
        return non_addr_lines[0]['text']

    #    (2순위) 전체 텍스트에서 회사명 패턴 재탐색 (폴백)
    #    예: "㈜OOO", "OOO(주)", "OO머티리얼", "OO테크" 등
    company_pattern = re.search(
        r'([가-힣A-Za-z]{2,}(?:머티리얼|테크|산업|정밀|소재|전자|화학|시스템|솔루션|(?:\(주\)|㈜)))',
        full_text
    )
    if company_pattern:
        return company_pattern.group(1)

    #    (3순위) 주소로 판정되지 않은 첫 줄 반환
    for l in line_texts:
        if not l['is_addr'] and len(l['text']) >= 2:
            return l['text']

    return ""


# ============================================================
# 메인 로직
# ============================================================
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
                    config='--psm 6'   # 표 구조에 유리
                )
                data_df = data_df[data_df.text.notnull() & (data_df.text.str.strip() != '')]
                data_df['conf'] = pd.to_numeric(data_df['conf'], errors='coerce').fillna(0)

                # ---------- 1. 수주번호 ----------
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', full_text)
                if order_match:
                    order_no = re.sub(r'[^A-Za-z0-9\-]', '', order_match.group(1).strip())
                else:
                    alt = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', full_text)
                    if alt:
                        order_no = alt.group(1).strip()

                # ---------- 2. 의뢰일자 ----------
                date = ""
                date_matches = re.findall(r'(20[2-9][0-9][-/.][0-9]{2}[-/.][0-9]{2})', full_text)
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

                # ---------- 3. 업체명 (핵심 수정) ----------
                vendor = extract_vendor_name(data_df, full_text)
                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # ---------- 4. 발주서번호 ----------
                po_no = ""
                po_match = re.search(r'(PO?[0-9]{8,})', full_text, re.IGNORECASE)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    alt_po = re.search(r'발주서[^\w]*번호[^\w]*([A-Za-z0-9]+)', full_text)
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

            # ---------- 디버깅용 (개발 중에만 True) ----------
            if st.checkbox("🔍 OCR 좌표 디버깅 보기"):
                st.dataframe(
                    data_df[['text', 'left', 'top', 'width', 'height', 'conf']]
                    .sort_values(by=['top', 'left'])
                )

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
