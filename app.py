import streamlit as st
import pytesseract
from PIL import Image
import pandas as pd
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
            
            with st.spinner("AI가 문서 좌표를 정밀 분석 중입니다..."):
                # 1. 단어별 좌표 데이터를 포함하여 추출 (영역 이탈 방지용)
                df = pytesseract.image_to_string(image, lang='kor+eng') # 전체 텍스트 수주/발주서용
                data_df = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME, lang='kor+eng')
                data_df = data_df[data_df.text.notnull() & (data_df.text.str.strip() != '')]

                # 2. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', df)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', df)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 3. [좌표 제한] 의뢰일자 추출 ('의뢰일자' 또는 'Issue Date'가 있는 행의 우측만 탐색)
                date = ""
                date_labels = data_df[data_df['text'].str.contains('의뢰일자|Issue|Date', na=False)]
                if not date_labels.empty:
                    d_row = date_labels.iloc[0]
                    d_top, d_left = d_row['top'], d_row['left']
                    
                    # 같은 행(top ±30 픽셀)이고 오른쪽에 있는 텍스트만 필터링
                    row_tokens = data_df[
                        (data_df['top'] >= d_top - 25) & 
                        (data_df['top'] <= d_top + 45) & 
                        (data_df['left'] > d_left)
                    ].sort_values(by=['left'])
                    
                    for _, r in row_tokens.iterrows():
                        w = r['text'].strip()
                        date_m = re.search(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', w)
                        if date_m:
                            date = date_m.group(1).replace('-', '').replace('.', '').replace('/', '')
                            break
                        digits = re.sub(r'[^0-9]', '', w)
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                # 만약 좌표로 못 찾았을 경우 일반 검색 보조
                if not date:
                    date_m2 = re.search(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', df)
                    if date_m2:
                        date = date_m2.group(1).replace('-', '').replace('.', '').replace('/', '')

                # 4. [좌표 제한] 업체명 추출 ('업체소재지'가 있는 행의 우측/위쪽 영역만 엄격히 제한)
                vendor = ""
                vendor_labels = data_df[data_df['text'].str.contains('업체소재지|Vendor|Address', na=False)]
                if not vendor_labels.empty:
                    v_row = vendor_labels.iloc[0]
                    v_top, v_left = v_row['top'], v_row['left']
                    
                    # '업체소재지' 셀과 동일하거나 바로 위쪽(상호명이 위치한 행), 그리고 오른쪽에 있는 단어들만 수집
                    cell_tokens = data_df[
                        (data_df['top'] >= v_top - 35) & 
                        (data_df['top'] <= v_top + 45) & 
                        (data_df['left'] > v_left - 20)
                    ].sort_values(by=['top', 'left'])
                    
                    for _, r in cell_tokens.iterrows():
                        w = r['text'].strip()
                        # 주소 단어, 라벨명, 특수문자 제외하고 순수 상호명 후보 포착
                        clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', w)
                        if len(clean_w) >= 2 and clean_w.lower() not in ['vendor', 'address', '업체소재지']:
                            if not any(loc in clean_w for loc in ["경상", "경기", "충청", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "전라", "제주", "창원", "시", "군", "구", "읍", "면", "동", "길", "로", "번지"]):
                                vendor = clean_w
                                break

                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # 5. 발주서번호 추출
                po_no = ""
                po_match = re.search(r'(P[0-9]{10,})', df)
                if po_match:
                    po_no = po_match.group(1).strip()
                else:
                    alt_po = re.search(r'발주서[^\w]*번호[^\w]*([A-Za-z0-9]+)', df)
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
