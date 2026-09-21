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
                text = pytesseract.image_to_string(image, lang='kor+eng', config='--psm 6')
                
                # 1. 수주번호 추출
                order_no = ""
                order_match = re.search(r'(H[0-9]{6}[A-Za-z0-9\-]+)', text)
                if order_match:
                    order_no = order_match.group(1).strip()
                else:
                    alt_order = re.search(r'수주번호[^\w]*([A-Za-z0-9\-]+)', text)
                    if alt_order:
                        order_no = alt_order.group(1).strip()

                # 2. [집중 개선] 의뢰일자 추출 (문서 내 모든 날짜 형태 유연 탐색)
                date = ""
                # 형태 A: 202X-XX-XX 또는 202X.XX.XX 또는 202X/XX/XX (구분자 포함)
                date_match = re.search(r'(20[2-9][0-9][\s\-./]*[0-9]{2}[\s\-./]*[0-9]{2})', text)
                if date_match:
                    # 숫자만 깔끔하게 추출하여 8자리로 만들기
                    raw_date = date_match.group(1)
                    digits_only = re.sub(r'[^0-9]', '', raw_date)
                    if len(digits_only) == 8:
                        date = digits_only
                
                # 만약 위에서 못 찾았을 경우 8자리 연속 숫자 탐색
                if not date:
                    all_8dig = re.findall(r'(20[2-9][0-9][0-9]{4})', text)
                    if all_8dig:
                        date = all_8dig[0]

                # 3. [집중 개선] 업체명 추출 ('업체소재지' 근처의 진짜 상호명 포착)
                vendor = ""
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                
                for idx, line in enumerate(lines):
                    if "업체소재지" in line or "Vendor" in line or "Address" in line:
                        # 해당 줄과 주변 줄(위/아래)을 합쳐서 상호명 후보군 수집
                        pool = []
                        if idx > 0: pool.append(lines[idx - 1])
                        pool.append(line)
                        if idx + 1 < len(lines): pool.append(lines[idx + 1])
                        if idx + 2 < len(lines): pool.append(lines[idx + 2])
                        
                        for p_line in pool:
                            # 라벨명 및 주소성 키워드, 특수문자 제거
                            cleaned = re.sub(r'업체소재지|Vendor|Address|[\(\)\-\.,0-9]', '', p_line).strip()
                            words = cleaned.split()
                            for w in words:
                                # 행정구역 이름이나 너무 짧은 글자가 아닌 순수 상호명 단어 채택
                                if len(w) >= 2 and not any(loc in w for loc in ["경상", "경기", "충청", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "강원", "전라", "제주", "시", "군", "구", "읍", "면", "동", "길", "로", "번지"]):
                                    vendor = w
                                    break
                            if vendor:
                                break
                    if vendor:
                        break

                # 예외 안전 장치: 문서 상단에서 의미 있는 한글/영문 단어 찾기
                if not vendor or len(vendor) < 2 or vendor in ["Lb", "Vendor", "Address"]:
                    for line in lines[:10]:
                        clean_line = re.sub(r'[^가-힣a-zA-Z]', '', line)
                        if len(clean_line) >= 2 and not any(k in clean_line for k in ["구매", "담당", "자재", "품질", "검사", "인수", "의뢰서", "보고서", "소재지", "Procurement", "Quality", "RECEIVING"]):
                            vendor = clean_line
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
