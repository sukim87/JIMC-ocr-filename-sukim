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
                
                # 1. 수주번호 추출 (Order No 또는 H로 시작하는 패턴)
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'(?:Order\s*No\.?|수주번호)[:\s]*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 ('Issue Date 의뢰일자' 또는 '의뢰일자' 키워드 뒤 8자리 또는 날짜 형식)
                date = ""
                date_match = re.search(r'(?:Issue\s*Date\s*의뢰일자|의뢰일자|Date)[\s\.:]*([0-9]{4}[-/.][0-9]{2}[-/.][0-9]{2})', text, re.IGNORECASE)
                if date_match:
                    date = date_match.group(1).strip().replace("-", "").replace(".", "").replace("/", "")
                else:
                    # 8자리 숫자로 붙어있는 날짜 탐색 (예: 20250416)
                    all_dates = re.findall(r'(20[2-9][0-9][0-9]{4})', text)
                    if all_dates:
                        date = all_dates[0]

                # 3. 업체명 추출 ('업체소재지' 키워드 근처에서 회사명 추출)
                vendor = ""
                # '업체소재지' 키워드 뒤나 전체 텍스트에서 주요 협력사 이름 직접 탐색
                if "신진볼텍" in text or "SHINJIN" in text.upper():
                    vendor = "신진볼텍"
                elif "동남" in text or "DONGNAM" in text.upper():
                    vendor = "동남"
                else:
                    # '업체소재지' 레이블 바로 옆의 텍스트 조각 추출 시도
                    vendor_match = re.search(r'업체소재지[^\n]*\n+([가-힣A-Za-z]+)', text)
                    if vendor_match:
                        vendor = vendor_match.group(1).strip()
                    else:
                        vendor = "업체명확인필요"

                # 4. 발주서번호 추출 ('Po No' 또는 '발주서 번호' 키워드 기준)
                po_no = ""
                po_match = re.search(r'(?:Po\s*No\.?|발주서\s*번호)[\s\.:]*([A-Za-z0-9]+)', text, re.IGNORECASE)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    alt_po = re.search(r'(P[0-9]{10,})', text)
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
