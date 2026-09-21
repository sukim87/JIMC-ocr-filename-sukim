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

                # 2. 의뢰일자 추출
                date = ""
                date_matches = re.findall(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', full_text)
                if date_matches:
                    for m in date_matches:
                        digits = re.sub(r'[^0-9]', '', m)
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                if not date:
                    date_label = data_df[data_df['text'].str.contains('의뢰일자|Issue|Date', na=False)]
                    if not date_label.empty:
                        d_row = date_label.iloc[0]
                        d_top, d_left = d_row['top'], d_row['left']
                        
                        date_tokens = data_df[
                            (data_df['top'] >= d_top - 10) & 
                            (data_df['top'] <= d_top + 55) & 
                            (data_df['left'] >= d_left - 40) &
                            (data_df['left'] <= d_left + 180)
                        ].sort_values(by=['top', 'left'])
                        
                        for _, r in date_tokens.iterrows():
                            w = r['text'].strip()
                            clean_w = re.sub(r'[^0-9\-/.]', '', w)
                            digits = re.sub(r'[^0-9]', '', clean_w)
                            
                            if len(digits) == 8 and digits.startswith('20'):
                                date = digits
                                break
                            elif len(digits) == 4:
                                date = "2025" + digits
                                break

                if not date:
                    for _, r in data_df.iterrows():
                        digits = re.sub(r'[^0-9]', '', r['text'])
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                # 3. 업체명 추출 (우측 칸 안에서 세로 좌표가 가장 높은 '최상단 첫 번째 줄'만 정밀 타겟팅)
                vendor = ""
                vendor_label = data_df[data_df['text'].str.contains('업체소재지|Vendor', na=False)]
                if not vendor_label.empty:
                    v_row = vendor_label.sort_values(by='top').iloc[0]
                    v_top, v_left, v_width = v_row['top'], v_row['left'], v_row['width']
                    
                    # '업체소재지' 레이블 우측 영역에 있는 텍스트들 수집
                    right_cell_left = v_left + v_width - 10
                    right_tokens = data_df[
                        (data_df['left'] >= right_cell_left) &
                        (data_df['top'] >= v_top - 20) &
                        (data_df['top'] <= v_top + 35)
                    ].sort_values(by=['top', 'left'])
                    
                    if not right_tokens.empty:
                        # 그중 가장 위에 있는 줄(가장 작은 top 값)을 가진 토큰 그룹만 추출
                        min_top = right_tokens['top'].min()
                        top_line_tokens = right_tokens[
                            (right_tokens['top'] >= min_top - 6) &
                            (right_tokens['top'] <= min_top + 6)
                        ].sort_values(by='left')
                        
                        extracted_words = []
                        for _, r in top_line_tokens.iterrows():
                            w = r['text'].strip()
                            if any(k in w.lower() for k in ['vendor', 'address', '업체소재지']):
                                continue
                            clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', w)
                            if len(clean_w) > 0:
                                extracted_words.append(clean_w)
                        
                        if extracted_words:
                            vendor = "".join(extracted_words)

                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # 4. 발주서번호 추출
                po_no = ""
                po_match = re.search(r'(PO?[0-9]{8,})', full_text, re.IGNORECASE)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    po_label = data_df[data_df['text'].str.contains('발주서|Po|No', na=False)]
                    if not po_label.empty:
                        for _, p_row in po_label.iterrows():
                            p_top, p_left = p_row['top'], p_row['left']
                            po_tokens = data_df[
                                (data_df['top'] >= p_top - 15) & 
                                (data_df['top'] <= p_top + 45) & 
                                (data_df['left'] >= p_left) &
                                (data_df['left'] <= p_left + 200)
                            ].sort_values(by=['top', 'left'])
                            
                            for _, r in po_tokens.iterrows():
                                w = r['text'].strip()
                                if re.search(r'P[A-Za-z0-9]{8,}', w, re.IGNORECASE):
                                    clean_po = re.sub(r'[^A-Za-z0-9]', '', w)
                                    if len(clean_po) >= 8:
                                        po_no = clean_po
                                        break
                            if po_no:
                                break

                    if not po_no:
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
