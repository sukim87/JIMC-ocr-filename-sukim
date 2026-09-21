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
                img_np = np.array(image)
                if len(img_np.shape) == 3:
                    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img_np
                
                processed_image = Image.fromarray(gray)

                # PSM 3(자동 페이지 분할)로 전체 텍스트 추출
                custom_config = r'--oem 3 --psm 3'
                full_text = pytesseract.image_to_string(processed_image, lang='kor+eng', config=custom_config)
                data_df = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DATAFRAME, lang='kor+eng', config=custom_config)
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
                    for _, r in data_df.iterrows():
                        digits = re.sub(r'[^0-9]', '', r['text'])
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break

                # 3. 업체명 추출 (관점 변경: '업체소재지' 키워드 주변이나 상호명 패턴을 텍스트 줄 단위로 탐색)
                vendor = ""
                lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                
                for i, line in enumerate(lines):
                    # '업체소재지'나 'Vendor'가 포함된 줄을 찾음
                    if '업체소재지' in line or 'Vendor' in line:
                        # 만약 같은 줄에 주소나 다른 텍스트가 길게 붙어있지 않고, 바로 윗줄이나 아랫줄에 상호명이 있는 경우 대비
                        # 보통 상호명이 '업체소재지' 우측 상단에 위치하므로, 해당 줄 또는 바로 윗줄을 검사
                        target_candidates = []
                        if i > 0:
                            target_candidates.append(lines[i-1])
                        target_candidates.append(line)
                        if i < len(lines) - 1:
                            target_candidates.append(lines[i+1])
                            
                        for candidate in target_candidates:
                            # 키워드 자체 제거
                            cleaned = candidate
                            for kw in ['업체소재지', 'Vendor', 'Address', 'vendor address', '결재']:
                                cleaned = cleaned.replace(kw, '')
                            
                            # 주소 관련 단어(시, 구, 로, 길, 동, 호 등)가 포함된 긴 주소 줄은 상호명이 아니므로 스킵
                            if any(addr_k in cleaned for addr_k in ['로', '길', '동', '호', '부산', '창원', '시', '구']):
                                continue
                                
                            clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', cleaned)
                            if len(clean_w) >= 2:
                                vendor = clean_w
                                break
                    if vendor:
                        break

                # 만약 위 방식으로도 못 찾았다면, 데이터프레임에서 '에스앤피' 같은 공장/업체명 키워드를 직접 전수 검색
                if not vendor or len(vendor) < 2:
                    for _, r in data_df.iterrows():
                        txt = r['text'].strip()
                        if '에스앤피' in txt or '머티리얼' in txt or '볼텍' in txt:
                            vendor = re.sub(r'[^가-힣a-zA-Z0-9]', '', txt)
                            break

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
