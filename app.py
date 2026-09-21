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
            
            with st.spinner("AI가 문서를 분석 중입니다..."):
                text = pytesseract.image_to_string(image, lang='kor+eng')
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                
                # 1. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. 의뢰일자 추출 (문서 내 날짜 패턴 최우선 탐색)
                date = ""
                # 날짜 패턴 전수 조사 (예: 2025-04-16, 2025.04.16 등)
                date_candidates = re.findall(r'(20[2-9][0-9][\s\-./]*[0-9]{2}[\s\-./]*[0-9]{2})', text)
                if date_candidates:
                    # 가장 먼저 발견된 유효한 날짜 사용
                    for dc in date_candidates:
                        digits = re.sub(r'[^0-9]', '', dc)
                        if len(digits) == 8 and digits.startswith('20'):
                            date = digits
                            break
                
                # 만약 못 찾았으면 '의뢰일자' 또는 'Issue Date' 주변 라벨 탐색
                if not date:
                    for idx, line in enumerate(lines):
                        if "의뢰일자" in line or "Issue" in line:
                            # 현재 줄 및 다음 줄들에서 숫자 조합 탐색
                            search_chunk = " ".join(lines[idx:idx+2])
                            d_match = re.search(r'([0-9]{4}[-/.][0-9]{2}[-/.][0-9]{2})', search_chunk)
                            if d_match:
                                date = re.sub(r'[^0-9]', '', d_match.group(1))
                                break

                # 3. 업체명 추출 (업체소재지 / Vendor Address 기준 강력 탐색)
                vendor = ""
                for idx, line in enumerate(lines):
                    if "업체소재지" in line or "Vendor" in line or "Address" in line:
                        # 해당 줄 및 바로 다음 줄까지 후보군으로 결합
                        target_chunk = line
                        if idx + 1 < len(lines):
                            target_chunk += " " + lines[idx + 1]
                        if idx + 2 < len(lines):
                            target_chunk += " " + lines[idx + 2]
                        
                        # 라벨 및 주소 키워드, 특수문자 제거 후 단어 추출
                        cleaned = re.sub(r'업체소재지|Vendor|Address|[\(\)\-\.,0-9]', '', target_chunk).strip()
                        words = cleaned.split()
                        
                        for w in words:
                            clean_w = re.sub(r'[^가-힣a-zA-Z0-9]', '', w)
                            if len(clean_w) >= 2 and clean_w.lower() not in ['vendor', 'address']:
                                # 행정구역 및 일반 명사 제외
                                if not any(loc in clean_w for loc in ["경상", "경기", "충청", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "전라", "제주", "창원", "시", "군", "구", "읍", "면", "동", "길", "로", "번지"]):
                                    vendor = clean_w
                                    break
                        if vendor:
                            break

                if not vendor or len(vendor) < 2:
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
