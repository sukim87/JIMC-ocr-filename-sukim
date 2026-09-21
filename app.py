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
                
                # 1. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_match_str = order_match.group(1).strip()
                    # OCR 오인식 방지 보정 (O -> 0 등)
                    order_no = order_match_str.replace('O', '0').replace('o', '0')
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 (문서 내 모든 날짜 후보를 찾아 첫 번째 것을 채택)
                date = ""
                # 구분자가 있는 날짜 패턴 (예: 2025-04-01, 2025.04.01 등)
                date_candidates = re.findall(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', text)
                if date_candidates:
                    date = date_candidates[0].strip().replace("-", "").replace(".", "").replace("/", "")
                else:
                    # 구분자 없는 8자리 날짜 패턴 (예: 20250401)
                    all_8digit = re.findall(r'(20[2-9][0-9][0-9]{4})', text)
                    if all_8digit:
                        date = all_8digit[0]

                # 3. 업체명 추출 (키워드 이후 텍스트에서 주소/우편번호 이전의 첫 단어 추출)
                vendor = ""
                # '업체소재지' 또는 'Vendor Address' 이후의 모든 텍스트를 대상로 설정
                pos = text.find("업체소재지")
                if pos == -1:
                    pos = text.find("Vendor Address")
                if pos == -1:
                    pos = text.find("Vendor")

                if pos != -1:
                    sub_text = text[pos:]
                    # 라벨 단어들 제거
                    sub_text = re.sub(r'업체소재지|Vendor\s*Address|Vendor', '', sub_text, flags=re.IGNORECASE).strip()
                    # 공백이나 줄바꿈으로 분리
                    tokens = sub_text.split()
                    for token in tokens:
                        clean_token = re.sub(r'[^가-힣a-zA-Z0-9]', '', token)
                        # 우편번호(숫자만 5~6자리)나 행정구역명, 괄호 등은 업체명이 아니므로 패스
                        if clean_token and not clean_token.isdigit() and len(clean_token) >= 2:
                            if not any(loc in clean_token for loc in ["경기", "경남", "경북", "충남", "충북", "전남", "전북", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "제주", "시", "구", "군", "동", "로", "길"]):
                                vendor = clean_token
                                break

                # 만약 위 방식으로도 못 찾았을 경우, 문서 상단에서 가장 유력한 한글/영문 상호명 추출
                if not vendor or len(vendor) < 2:
                    lines = text.split('\n')
                    for line in lines[:8]:
                        cleaned_line = re.sub(r'[^가-힣a-zA-Z]', '', line)
                        if len(cleaned_line) >= 2 and not any(k in cleaned_line for k in ["구매", "담당", "자재", "품질", "검사", "인수", "의뢰서", "보고서", "소재지", "Procurement", "Quality"]):
                            vendor = cleaned_line
                            break

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
