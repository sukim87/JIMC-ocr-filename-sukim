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
                data_df = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME, lang='kor+eng')
                data_df = data_df[data_df.text.notnull() & (data_df.text.str.strip() != '')]

                # 1. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', full_text)
                if order_match:
                    order_no = re.sub(r'[^A-Za-z0-9\-]', '', order_match.group(1).strip())
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', full_text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 (최우선: 전체 텍스트에서 20xx-xx-xx 형태의 날짜를 무조건 찾아냄)
                date = ""
                # 다양한 날짜 포맷 (예: 2025-04-01, 2025.04.01, 2025/04/01) 매칭
                date_matches = re.findall(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', full_text)
                if date_matches:
                    # 첫 번째로 발견된 유효한 8자리 날짜 사용
                    for m in date_matches:
                        digits = re.sub(r'[^0-9]', '', m)
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                # 만약 위에서 못 찾았을 경우 데이터프레임에서 직접 날짜 패턴 탐색
                if not date:
                    for _, r in data_df.iterrows():
                        w = r['text'].strip()
                        date_m = re.search(r'([0-9]{4}[-/.][0-9]{2}[-/.][0-9]{2})', w)
                        if date_m:
                            digits = re.sub(r'[^0-9]', '', date_m.group(1))
                            if len(digits) == 8 and digits.startswith('20'):
                                date = digits
                                break

                # 3. 업체명 추출: '업체소재지' 레이블 옆 칸에서 주소는 확실히 제외하고 상호명만 추출
                vendor = ""
                vendor_label = data_df[data_df['text'].str.contains('업체소재지|Vendor', na=False)]
                if not vendor_label.empty:
                    v_row = vendor_label.iloc[0]
                    v_top, v_left = v_row['top'], v_row['left']
                    
                    vendor_tokens = data_df[
                        (data_df['top'] >= v_top - 15) & 
                        (data_df['top'] <= v_top + 45) & 
                        (data_df['left'] > v_left + v_row['width'] - 10)
                    ].sort_values(by=['top', 'left'])
                    
                    extracted_words = []
                    for _, r in vendor_tokens.iterrows():
                        w = r['text'].strip()
                        if any(addr_start in w for addr_start in ["경기도", "경상", "충청", "전라", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "제주", "시", "군", "구", "읍", "면", "동", "로", "길", "호"]):
                            break
                        
                        clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', w)
                        if len(clean_w) >= 2 and clean_w.lower() not in ['vendor', 'address', '업체소재지']:
                            extracted_words.append(clean_w)
                    
                    if extracted_words:
                        vendor = "".join(extracted_words)

                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # 4. 발주서번호 추출
                po_no = ""
                po_match = re.search(r'(P[0-9]{10,})', full_text)
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

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
