import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# 페이지 기본 설정
st.set_page_config(
    page_title="하나로 2차 냉각계통 열평형 및 헌팅 방지 제어기",
    page_icon="⚛️",
    layout="wide"
)

# 계통 상수 정의
MARGIN_TEMP = 32.0       # 열교환기 2차측 입구 온도 안전 상한선 (℃)
MAX_BASIN_LEVEL = 3.9   # 수조 최대 수위 한계 (m)
TARGET_BASIN_LEVEL = 3.7 # 권장 목표 수위 (m)

# -----------------------------------------------------------------------------
# 세션 상태 초기화
# -----------------------------------------------------------------------------
if 'history_log' not in st.session_state:
    st.session_state.history_log = pd.DataFrame(columns=[
        '시각', '출력(MW)', '입구온도(℃)', '수위(m)', 
        '평형상태', '팬지시', '밸브(%)', '운전메모'
    ])

# -----------------------------------------------------------------------------
# [열평형 & 헌팅 방지] 핵심 제어 연산 함수
# -----------------------------------------------------------------------------
def calculate_equilibrium_control(reactor_mw, current_temp, current_level, amb_temp=25.0):
    """
    1. 원자로 출력과 방출 열량을 1:1 매칭하여 온도가 오르내리지 않도록 평형 팬 조합 산출
    2. 불필요한 온/오프 헌팅을 막기 위해 마진과 부하 기준 고정형 제어 지시 생성
    """
    margin_left = MARGIN_TEMP - current_temp
    
    # 1. 비상/임계 구간 (31.5℃ 이상 또는 마진 임박)
    if current_temp >= 31.5 or margin_left <= 0.5:
        return {
            "fans": 4, "speed": "HIGH", "states": [2, 2, 2, 2],
            "status": "🚨 [비상] 안전 마진 임계", "color": "red",
            "msg": "32.0℃ 마진 방어를 위해 즉시 모든 팬(4대) 고속 풀기동 유지",
            "equilibrium": "열축적 위험 (강제 방출 필요)"
        }

    # 2. 외기 온도를 반영한 팬 조합별 방출 능력 모델링 (MW 기준)
    efficiency_factor = max(0.7, 1.0 - (amb_temp - 20.0) * 0.015)
    
    cap_1_low  = 12.0 * efficiency_factor
    cap_2_low  = 22.0 * efficiency_factor
    cap_4_low  = 28.0 * efficiency_factor
    cap_2_high = 32.0 * efficiency_factor
    
    required_heat = reactor_mw
    
    # 3. 평형점 탐색 (헌팅 방지를 위해 조건별 고정 조합 지시)
    if required_heat <= 0:
        active_fans, speed, states = 0, "OFF", [0, 0, 0, 0]
        eq_status = "정지 평형"
        msg = "원자로 정지: 팬 가동 중지 및 자연 수심 유지"
        status, color = "STOP", "gray"
    elif required_heat <= cap_1_low:
        active_fans, speed, states = 1, "LOW", [1, 0, 0, 0]
        eq_status = "✨ 완벽 열평형 (Steady-State)"
        msg = f"팬 1대 저속 기동으로 {required_heat}MW 열량 1:1 완벽 상쇄 (온도 고정)"
        status, color = "BALANCED", "green"
    elif required_heat <= cap_2_low:
        active_fans, speed, states = 2, "LOW", [1, 1, 0, 0]
        eq_status = "✨ 완벽 열평형 (Steady-State)"
        msg = f"팬 2대 저속 기동으로 {required_heat}MW 열량 1:1 완벽 상쇄 (온도 고정)"
        status, color = "BALANCED", "green"
    elif required_heat <= cap_4_low:
        active_fans, speed, states = 4, "LOW", [1, 1, 1, 1]
        eq_status = "✨ 완벽 열평형 (Steady-State)"
        msg = f"팬 4대 저속 기동으로 {required_heat}MW 열량 1:1 완벽 상쇄 (온도 고정)"
        status, color = "BALANCED", "green"
    elif required_heat <= cap_2_high:
        active_fans, speed, states = 2, "HIGH", [2, 2, 0, 0]
        eq_status = "✨ 완벽 열평형 (Steady-State)"
        msg = f"팬 2대 고속 기동으로 {required_heat}MW 열량 1:1 완벽 상쇄 (온도 고정)"
        status, color = "BALANCED", "green"
    else:
        active_fans, speed, states = 4, "HIGH", [2, 2, 2, 2]
        eq_status = "✨ 완벽 열평형 (Steady-State)"
        msg = f"팬 4대 고속 기동으로 최대 출력({required_heat}MW) 열량 상쇄 평형 유지"
        status, color = "BALANCED", "green"

    return {
        "fans": active_fans, "speed": speed, "states": states,
        "status": status, "color": color, "msg": msg, "equilibrium": eq_status
    }

def calculate_stable_valve(reactor_mw, current_level):
    """
    증발량에 따른 잔류 유량을 계산하고, 수위가 목표치(3.7m) 근처일 때
    밸브 %를 고정하여 진동(Hunting)을 원천 차단
    """
    if current_level >= MAX_BASIN_LEVEL:
        return 0.0, "🔴 [범람 경계] 수위 3.9m 한계 도달로 보급수 밸브 0% 완전 차단"
    
    evaporation_flow = reactor_mw * 1.5  # 출력 비례 시간당 증발량 추정
    level_diff = TARGET_BASIN_LEVEL - current_level
    
    # 수위 오차가 ±0.02m 이내라면 밸브를 흔들지 않고 고정
    if abs(level_diff) <= 0.02:
        return 10.0, f"🟢 [수위 평형] 증발량 대응 및 수위 안정화: 보급수 밸브 10% 고정 유지"
    
    base_valve_pct = (evaporation_flow / 50.0) * 100.0
    corrected_pct = base_valve_pct + (level_diff * 150.0)
    final_pct = min(100.0, max(5.0, corrected_pct))
    
    return round(final_pct, 1), f"🔵 [수위 보정] 목표 수위(3.7m) 수렴을 위해 보급수 밸브 {round(final_pct, 1)}% 고정 조절"

# -----------------------------------------------------------------------------
# Streamlit UI 레이아웃
# -----------------------------------------------------------------------------
st.title("⚛️ 하나로(HANARO) 2차 냉각계통 평형 제어 & 가이드 툴")
st.caption("팬과 밸브의 잦은 헌팅을 방지하고, 온도가 오르내리지 않는 평형 상태의 조작 수치를 안내합니다.")

st.sidebar.header("🎛️ 운전 조건 입력 (Input)")
input_power = st.sidebar.select_slider("원자로 열출력 (MW)", options=[0, 10, 20, 27, 30], value=27)
input_temp = st.sidebar.slider("열교환기 2차측 입구 온도 (℃)", 25.0, 33.0, 29.0, 0.1)
input_level = st.sidebar.slider("수조(Basin) 수위 (m)", 3.00, 4.00, 3.70, 0.01)
amb_temp = st.sidebar.slider("외부 대기 온도 (℃)", 10.0, 35.0, 22.0, 0.5)

# 제어 연산
control_res = calculate_equilibrium_control(input_power, input_temp, input_level, amb_temp)
valve_pct, valve_msg = calculate_stable_valve(input_power, input_level)
margin_left = round(MARGIN_TEMP - input_temp, 2)

# 로그 기록 버튼
st.sidebar.divider()
if st.sidebar.button("💾 운전 결과 기록 및 피드백 저장"):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_log = {
        '시각': now_str, '출력(MW)': input_power, '입구온도(℃)': input_temp, '수위(m)': input_level,
        '평형상태': control_res['equilibrium'], '팬지시': f"팬 {control_res['fans']}대 [{control_res['speed']}]",
        '밸브(%)': f"{valve_pct}%", '운전메모': control_res['msg']
    }
    st.session_state.history_log = pd.concat([st.session_state.history_log, pd.DataFrame([new_log])], ignore_index=True)
    st.sidebar.success("기록 완료! 실제 움직임 피드백을 검토해보세요.")

# KPI 메트릭 카드
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("원자로 열출력", f"{input_power} MW", delta="발생 열부하")
with col2:
    st.metric("추천 팬 조작 지시", f"{control_res['fans']} 대 [{control_res['speed']}]", delta=control_res['equilibrium'])
with col3:
    st.metric("열교환기 입구 온도", f"{input_temp} ℃", delta=f"안전 마진 {margin_left} ℃", delta_color="inverse" if margin_left < 1.0 else "normal")
with col4:
    st.metric("추천 밸브 조작 지시", f"{valve_pct} %", delta="수위 평형 유지")

st.divider()

# 메인 UI 지시 패널
left_col, right_col = st.columns([1, 1])

with left_col:
    st.subheader("📢 현장 조작 지시 가이드 (Output)")
    st.markdown(f"""
    <div style="padding: 18px; border-radius: 10px; background-color: #f0f2f6; border-left: 6px solid {control_res['color']};">
        <h3>{control_res['equilibrium']}</h3>
        <p style="font-size: 16px;"><b>🌀 팬 조작 지시:</b> {control_res['msg']}</p>
        <p style="font-size: 16px;"><b>💧 밸브 조작 지시:</b> {valve_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.write("#### 🌀 팬 1~4호기 고정 상태 가이드")
    f1, f2, f3, f4 = st.columns(4)
    speed_labels = {0: "OFF ⚪", 1: "저속(고정) 🟢", 2: "고속(고정) 🔴"}
    
    f1.info(f"**팬 1호기**\n\n{speed_labels[control_res['states'][0]]}")
    f2.info(f"**팬 2호기**\n\n{speed_labels[control_res['states'][1]]}")
    f3.info(f"**팬 3호기**\n\n{speed_labels[control_res['states'][2]]}")
    f4.info(f"**팬 4호기**\n\n{speed_labels[control_res['states'][3]]}")

with right_col:
    st.subheader("📊 온도 마진 현황")
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = input_temp,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': f"2차측 입구 온도 (목표 평형 / 한계: 32.0℃)"},
        gauge = {
            'axis': {'range': [25, 34]},
            'bar': {'color': control_res['color']},
            'steps': [
                {'range': [25, 29], 'color': "lightgreen"},
                {'range': [29, 30.5], 'color': "khaki"},
                {'range': [30.5, 32], 'color': "orange"},
                {'range': [32, 34], 'color': "salmon"}
            ],
            'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 32.0}
        }
    ))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# 로그 및 피드백 테이블
st.subheader("📋 운전 기록 및 피드백 로그")
if not st.session_state.history_log.empty:
    st.dataframe(st.session_state.history_log, use_container_width=True)
    csv_data = st.session_state.history_log.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 운전 기록 CSV 다운로드", data=csv_data, file_name="hanaro_feedback_log.csv", mime="text/csv")
else:
    st.info("조작 가이드를 참고하여 수치를 입력하고 [💾 운전 결과 기록 및 피드백 저장]을 눌러 데이터를 쌓아보세요.")
