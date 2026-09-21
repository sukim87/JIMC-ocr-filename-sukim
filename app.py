import streamlit as st
import pytesseract
from PIL import Image
import numpy as np
import cv2
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
                # 1. 핵심 해결책: 이미지 2배 확대 (한글 '에스앤피머티리얼' 획 깨짐 방지)
                new_width = int(image.width * 2)
                new_height = int(image.height * 2)
                image = image.resize((new_width, new_height), Image.LANCZOS)

                # 2. 흑백 그레이스케일 처리 (이진화는 한글을 망가뜨리므로 제외)
                img_np = np.array(image)
                if len(img_np.shape) == 3:
                    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img_np
                
                processed_image = Image.fromarray(gray)

                # 3. OCR 텍스트 추출 (표 형식에 유리한 psm 6 적용)
                custom_config = r'--oem 3 --psm 6'
                full_text = pytesseract.image_to_string(processed_image, lang='kor+eng', config=custom_config)
                data_df = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DATAFRAME, lang='kor+eng', config=custom_config)
                data_df = data_df[data_df.text.notnull() & (data_df.text.str.strip() != '')]

                # --- 항목 추출 ---
                # 1. 수주번호
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', full_text)
                if order_match:
                    order_no = re.sub(r'[^A-Za-z0-9\-]', '', order_match.group(1).strip())
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', full_text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자
                date = ""
                date_matches = re.findall(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', full_text)
                if date_matches:
                    for m in date_matches:
                        digits = re.sub(r'[^0-9]', '', m)
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break
                if not date:
                    for _, r in data_df.iterrows():
                        digits = re.sub(r'[^0-9]', '', r['text'])
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                # 3. 업체명 추출 (핵심 로직: '업체소재지' 기준 철저한 영역 커팅)
                vendor = ""
                # '업체소재지' 키워드 좌표 찾기
                vendor_label = data_df[data_df['text'].str.contains('업체소재지', na=False)]
                if not vendor_label.empty:
                    v_row = vendor_label.iloc[0]
                    v_top, v_left, v_width = v_row['top'], v_row['left'], v_row['width']
                    
                    # 검색 영역을 완벽히 통제
                    # 좌측: '업체소재지' 라벨이 끝나는 지점 + 약간의 여백 (결재란 차단)
                    search_left = v_left + v_width + 10
                    search_right = search_left + 800  # 우측으로 넉넉히
                    
                    # 상하: '업체소재지' 글자와 동일한 라인 (아랫줄 주소 차단)
                    search_top = v_top - 20
                    search_bottom = v_top + 40
                    
                    target_tokens = data_df[
                        (data_df['left'] >= search_left) & 
                        (data_df['left'] <= search_right) & 
                        (data_df['top'] >= search_top) & 
                        (data_df['top'] <= search_bottom)
                    ].sort_values(by=['left'])
                    
                    extracted_words = []
                    for _, r in target_tokens.iterrows():
                        w = r['text'].strip()
                        # 혹시 모를 주소 관련 단어 필터링
                        if any(addr_k in w for addr_k in ['부산', '창원', '시', '구', '동', '번길']):
                            continue
                        # 특수문자 제거 후 한글, 영어만 추출
                        clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', w)
                        
                        # 잘못 들어온 '결', '재' 등 찌꺼기 글자 방어
                        if len(clean_w) > 0 and clean_w not in ['결', '재', '결재', 'Vendor']:
                            extracted_words.append(clean_w)
                            
                    if extracted_words:
                        vendor = "".join(extracted_words)

                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # 4. 발주서번호
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

    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
