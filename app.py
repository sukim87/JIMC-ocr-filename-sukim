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
                # OCR 설정 보완 (공백과 줄바꿈 유지 최적화)
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

                # 2. [완전 신규 방식] 의뢰일자 추출: 문서 내 모든 날짜 형태 강력 탐색 후 첫 번째 값 확정
                date = ""
                # 형태 1: YYYY-MM-DD 또는 YYYY.MM.DD 또는 YYYY/MM/DD
                date_match = re.search(r'(20[2-9][0-9][-/.][0-9]{2][-/.][0-9]{2})', text)
                if date_match:
                    date = date_match.group(1).strip().replace("-", "").replace(".", "").replace("/", "")
                else:
                    # 형태 2: 202X로 시작하는 붙어있는 8자리 숫자
                    all_8digit = re.findall(r'(20[2-9][0-9][0-9]{4})', text)
                    if all_8digit:
                        date = all_8digit[0]

                # 3. [완전 신규 방식] 업체명 추출: '업체소재지' 근처 상단 영역 탐색
                vendor = ""
                # 텍스트 라인별로 쪼개서 '업체소재지'나 'Vendor'가 포함된 줄 주변 탐색
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                
                for idx, line in enumerate(lines):
                    if "업체소재지" in line or "Vendor" in line:
                        # 바로 위쪽 줄이나 아래쪽 줄에서 주소(시/도)가 포함되지 않은 순수 상호명 후보 탐색
                        search_pool = []
                        if idx > 0: search_pool.append(lines[idx - 1])
                        if idx + 1 < len(lines): search_pool.append(lines[idx + 1])
                        search_pool.append(line)
                        
                        for pool_line in search_pool:
                            # 키워드 및 주소성 단어, 특수문자 제거 후 남은 단어 추출
                            cleaned = re.sub(r'업체소재지|Vendor|Address|[0-9\(\)\-\.]', '', pool_line).strip()
                            words = cleaned.split()
                            for w in words:
                                if len(w) >= 2 and not any(loc in w for loc in ["경상남도", "경기도", "충청도", "서울시", "부산시", "대구시", "인천시", "광주시", "대전시", "울산시", "강원도", "전라도", "제주시", "시", "도", "군", "구", "읍", "면", "동", "길", "로", "번지"]):
                                    vendor = w
                                    break
                            if vendor:
                                break
                    if vendor:
                        break

                # 만약 위 방식으로도 못 찾았을 경우, 문서 상단 10줄 내에서 가장 상호명스러운 텍스트 추출
                if not vendor or len(vendor) < 2:
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
