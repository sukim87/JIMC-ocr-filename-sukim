import streamlit as st
import pytesseract
from PIL import Image
import pandas as pd
import re
import os

os.environ['PATH'] += os.pathsep + '/usr/bin'

st.set_page_config(page_title="인수검사서 파일명 자동 생성기", page_icon="📄", layout="centered")

st.title("📄 인수검사서 파일명 자동 생성기")
st.write("스캔된 PDF나 이미지 파일을 업로드하면 문서 표 영역을 정밀 잘라내어 분석합니다.")
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
            
            with st.spinner("AI가 표 영역을 잘라내어 정밀 분석 중입니다..."):
                img_w, img_h = image.size
                full_text = pytesseract.image_to_string(image, lang='kor+eng')
                data_df = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME, lang='kor+eng')
                data_df = data_df[data_df.text.notnull() & (data_df.text.str.strip() != '')]

                # 1. 수주번호 추출 (기존 방식 유지 - 정확함)
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', full_text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', full_text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. [ROI 크로핑] 의뢰일자 추출 ('의뢰일자' 또는 'Issue' 키워드 오른쪽 칸 잘라내기)
                date = ""
                date_label = data_df[data_df['text'].str.contains('의뢰일자|Issue|Date', na=False)]
                if not date_label.empty:
                    dl_row = date_label.iloc[0]
                    # 키워드 우측 칸 영역 설정 (좌측 끝 ~ 우측으로 적당한 폭, 상하 여유)
                    crop_left = max(0, dl_row['left'] + dl_row['width'] - 10)
                    crop_top = max(0, dl_row['top'] - 10)
                    crop_right = min(img_w, crop_left + int(img_w * 0.25)) # 대략 25폭
                    crop_bottom = min(img_h, dl_row['top'] + dl_row['height'] + 20)
                    
                    date_crop = image.crop((crop_left, crop_top, crop_right, crop_bottom))
                    date_crop_text = pytesseract.image_to_string(date_crop, lang='kor+eng', config='--psm 7')
                    
                    # 잘라낸 영역에서 날짜 추출
                    d_m = re.search(r'([0-9]{4}[-/.][0-9]{2}[-/.][0-9]{2})', date_crop_text)
                    if d_m:
                        date = re.sub(r'[^0-9]', '', d_m.group(1))
                    else:
                        digits = re.sub(r'[^0-9]', '', date_crop_text)
                        if len(digits) >= 8 and digits.startswith('20'):
                            date = digits[:8]

                # 보조 Fallback (좌표 탐색 실패 시 전체 텍스트 검색)
                if not date:
                    dm_all = re.search(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', full_text)
                    if dm_all:
                        date = re.sub(r'[^0-9]', '', dm_all.group(1))

                # 3. [ROI 크로핑] 업체명 추출 ('업체소재지' 키워드 바로 오른쪽 칸 잘라내기)
                vendor = ""
                vendor_label = data_df[data_df['text'].str.contains('업체소재지|Vendor', na=False)]
                if not vendor_label.empty:
                    vl_row = vendor_label.iloc[0]
                    # '업체소재지' 우측 칸 영역 설정 (상호명이 들어있는 위치)
                    crop_left = max(0, vl_row['left'] + vl_row['width'] - 15)
                    crop_top = max(0, vl_row['top'] - 15)
                    crop_right = min(img_w, crop_left + int(img_w * 0.35)) # 적당한 가로 폭
                    crop_bottom = min(img_h, vl_row['top'] + 50) # 상호명과 주소 첫 줄 포함
                    
                    vendor_crop = image.crop((crop_left, crop_top, crop_right, crop_bottom))
                    vendor_crop_text = pytesseract.image_to_string(vendor_crop, lang='kor+eng', config='--psm 6')
                    
                    # 잘라낸 영역의 첫 번째 줄 또는 의미 있는 상호명 추출
                    lines = [l.strip() for l in vendor_crop_text.split('\n') if l.strip()]
                    for l in lines:
                        cleaned = re.sub(r'[^가-힣a-zA-Z0-9]', '', l)
                        if len(cleaned) >= 2 and cleaned.lower() not in ['vendor', 'address', '업체소재지']:
                            # 행정구역 및 주소 단어 제외하고 첫 번째로 등장하는 진짜 상호명 채택
                            if not any(loc in cleaned for loc in ["경상", "경기", "충청", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "전라", "제주", "창원", "시", "군", "구", "읍", "면", "동", "길", "로", "번지"]):
                                vendor = cleaned
                                break
                    # 만약 첫 줄에 걸러지지 않았다면 정제된 첫 번째 텍스트 사용
                    if not vendor and lines:
                        for l in lines:
                            c = re.sub(r'[^가-힣a-zA-Z0-9]', '', l)
                            if len(c) >= 2 and c.lower() not in ['vendor', 'address', '업체소재지']:
                                vendor = c
                                break

                if not vendor or len(vendor) < 2:
                    vendor = "업체명확인필요"

                # 4. 발주서번호 추출 (기존 방식 유지 - 정확함)
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
