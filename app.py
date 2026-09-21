import streamlit as st
import pytesseract
from PIL import Image
import re
import os

os.environ['PATH'] += os.pathsep + '/usr/bin'

st.set_page_config(page_title="인수검사서 파일명 자동 생성기", page_icon="📄", layout="centered")

st.title("📄 인수검사서 파일명 자동 생성기")
st.write("스캔된 PDF나 이미지 파일을 업로드하면 문서 내용을 분석하여 올바른 파일명을 만들어 줍니다.")
st.markdown("---")

uploaded_file = st.file_uploader("파일을 업로드하세요 (PDF, JPG, PNG)", type=["pdf", "png", "jpg", "jpeg"])

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
                text = pytesseract.image_to_string(image, lang='kor+eng')
                
                # 1. 수주번호 추출 (H로 시작하는 패턴 우선 탐색)
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 ('의뢰일자' 또는 'Issue Date' 키워드 주변 바운더리 탐색)
                date = ""
                date_bound_match = re.search(r'(?:의뢰일자|Issue\s*Date)[^\d]*(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', text, re.IGNORECASE)
                if date_bound_match:
                    date = date_bound_match.group(1).strip().replace("-", "").replace(".", "").replace("/", "")
                else:
                    # 문서 내 첫 번째로 등장하는 날짜 형태 탐색
                    date_match = re.search(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', text)
                    if date_match:
                        date = date_match.group(1).strip().replace("-", "").replace(".", "").replace("/", "")

                # 3. 업체명 추출 ('업체소재지' / 'Vendor Address' 키워드 바운더리 내 상호명 동적 추출)
                vendor = ""
                # '업체소재지' 또는 'Vendor Address' 바로 뒤의 셀 영역 텍스트 추출
                vendor_bound = re.search(r'(?:업체소재지|Vendor\s*Address)[^\n]*\n+([^\n]+)', text, re.IGNORECASE)
                if vendor_bound:
                    raw_vendor_line = vendor_bound.group(1).strip()
                    # 만약 주소(경상남도 등)가 함께 잡혔다면, 주소 앞의 상호명만 분리
                    # 예: "신진볼텍 경상남도 창원시..." -> "신진볼텍" 추출
                    clean_vendor = re.split(r'(?:경상남도|경기도|충청도|서울시|부산시|대구시|인천시|광주시|대전시|울산시|강원도|전라도|제주시|[0-9]{2,})', raw_vendor_line)[0].strip()
                    if clean_vendor and len(clean_vendor) > 1:
                        vendor = clean_vendor
                    else:
                        vendor = raw_vendor_line.split()[0] if raw_vendor_line else ""

                # 바운더리에서 못 찾았을 경우 상단 영역에서 첫 번째 유효 상호명 동적 탐색 (하드코딩 없음)
                if not vendor or len(vendor) < 2:
                    lines = text.split('\n')
                    for line in lines[:10]:
                        cleaned = re.sub(r'[^가-힣a-zA-Z]', '', line)
                        if len(cleaned) >= 2 and not any(k in cleaned for k in ["구매", "담당", "자재", "품질", "검사", "인수", "의뢰서", "보고서", "소재지", "Vendor"]):
                            vendor = cleaned
                            break

                # 4. 발주서번호 추출 (P로 시작하는 번호 탐색)
                po_no = ""
                po_match = re.search(r'(P[0-9]{10,})', text)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    alt_po = re.search(r'발주서[^\w]*번호[^\w]*([A-Za-z0-9]+)', text)
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

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
