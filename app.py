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
                # PSM 3 (기본 자동 페이지 분할) 또는 PSM 11(스파르탄 텍스트)로 전체 텍스트 추출
                text = pytesseract.image_to_string(image, lang='kor+eng', config='--psm 3')
                
                # [디버깅용] OCR이 실제로 읽어낸 원본 텍스트를 화면에 그대로 보여줍니다.
                with st.expander("🔍 OCR이 읽어낸 원본 텍스트 보기 (확인용)"):
                    st.text(text)
                
                # 1. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 (문서 내 모든 8자리 또는 날짜 형태 전수 조사 후 매칭)
                date = ""
                # 날짜 후보 모두 찾기 (예: 2025-04-16, 2025.04.16 등)
                date_candidates = re.findall(r'(20[2-9][0-9][\s\-./]*[0-9]{2}[\s\-./]*[0-9]{2})', text)
                if date_candidates:
                    # 첫 번째로 매칭된 날짜에서 숫자만 추출
                    digits = re.sub(r'[^0-9]', '', date_candidates[0])
                    if len(digits) == 8:
                        date = digits
                
                if not date:
                    all_8 = re.findall(r'(20[2-9][0-9][0-9]{4})', text)
                    if all_8:
                        date = all_8[0]

                # 3. 업체명 추출 (텍스트 전체에서 알려진 상호명이나 패턴 강제 매칭)
                vendor = ""
                # 만약 텍스트 내에 '신진볼텍'이나 '대진상사' 같은 상호명이 포함되어 있다면 직접 잡아내기 위한 리스트 검사
                known_vendors = ["신진볼텍", "대진상사", "성화산업", "덕영테크"]
                for kv in known_vendors:
                    if kv in text:
                        vendor = kv
                        break
                
                # 리스트에 없으면 '업체소재지' 근처의 단어들 중 행정구역이 아닌 첫 번째 한글 단어 강제 추출
                if not vendor:
                    words = text.split()
                    for i, w in enumerate(words):
                        if "업체소재지" in w or "Vendor" in w:
                            # 뒤에 오는 단어들 중 주소가 아닌 첫 단어 선택
                            for next_w in words[i+1:i+10]:
                                clean_nw = re.sub(r'[^가-힣]', '', next_w)
                                if len(clean_nw) >= 2 and not any(loc in clean_nw for loc in ["경상남도", "경기도", "충청도", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "전라", "제주", "시", "군", "구", "읍", "면", "동", "길", "로"]):
                                    vendor = clean_nw
                                    break
                            if vendor:
                                break

                if not vendor:
                    vendor = "업체명확인필요"

                # 4. 발주서번호 추출
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
