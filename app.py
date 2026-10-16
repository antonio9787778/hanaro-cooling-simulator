import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# 페이지 기본 설정
st.set_page_config(
    page_title="하나로(HANARO) 2차 냉각계통 최적 제어 시뮬레이터",
    page_icon="⚛️",
    layout="wide"
)

# 계통 상수 정의
MARGIN_TEMP = 32.0       # 열교환기 2차 측 입구 온도 안전 상한선 (℃)
MAX_BASIN_LEVEL = 3.9   # 수조 최대 수위 한계 (m)
TARGET_BASIN_LEVEL = 3.7 # 권장 목표 수위 (m)

# -----------------------------------------------------------------------------
# 세션 상태(데이터 저장용) 초기화
# -----------------------------------------------------------------------------
if 'history_log' not in st.session_state:
    # 히스토리 데이터를 저장할 빈 DataFrame 생성
    st.session_state.history_log = pd.DataFrame(columns=[
        '시각', '열출력(MW)', '입구온도(℃)', '온도변화율(℃/min)', 
        '수조수위(m)', '추천팬가동', '팬속도', '보급수밸브(%)', '상태'
    ])

# -----------------------------------------------------------------------------
# 제어 및 계산 로직 함수
# -----------------------------------------------------------------------------
def calculate_optimal_fans(current_temp, temp_rate):
    """32.0℃ 마진을 준수하며 팬 가동을 최소화하는 알고리즘"""
    margin_gap = MARGIN_TEMP - current_temp
    
    # 1. 비상/임계 (31.5℃ 이상) -> 전면 고속
    if current_temp >= 31.5 or margin_gap <= 0.5:
        return {
            "active_fans": 4, "speed": "HIGH", "states": [2, 2, 2, 2],
            "status": "CRITICAL", "color": "red",
            "msg": "⚠️ 위험! 32.0℃ 마진 돌파 직전입니다. 모든 팬(4대)을 고속 가동합니다."
        }
    # 2. 경계 (30.5℃ ~ 31.5℃)
    elif current_temp >= 30.5:
        if temp_rate > 0:
            return {
                "active_fans": 4, "speed": "LOW", "states": [1, 1, 1, 1],
                "status": "WARNING", "color": "orange",
                "msg": "🟠 경고! 온도가 상승 중입니다. 팬 4대 저속 가동으로 대응합니다."
            }
        else:
            return {
                "active_fans": 2, "speed": "HIGH", "states": [2, 2, 0, 0],
                "status": "WARNING", "color": "orange",
                "msg": "🟠 경고! 팬 2대 고속 가동으로 32.0℃ 방어를 유지합니다."
            }
    # 3. 주의 (29.0℃ ~ 30.5℃)
    elif current_temp >= 29.0:
        return {
            "active_fans": 2, "speed": "LOW", "states": [1, 1, 0, 0],
            "status": "CAUTION", "color": "gold",
            "msg": "🟡 주의! 마진 여유가 있습니다 (+1.5℃ 이상). 팬 2대 저속으로 충분합니다."
        }
    # 4. 안정 (29.0℃ 미만) -> 팬 가동 최소화
    else:
        return {
            "active_fans": 1, "speed": "LOW", "states": [1, 0, 0, 0],
            "status": "STABLE", "color": "green",
            "msg": "🟢 안정! 마진 여유가 넉넉합니다. 팬 1대 저속 가동으로 전력 및 장비 피로도를 최소화합니다."
        }

def calculate_makeup_valve(current_level):
    """3.9m 범람 방지 보급수 밸브 % 제어"""
    if current_level >= MAX_BASIN_LEVEL:
        return 0.0, "🔴 범람 위험! 밸브 차단 (0%)"
    
    level_error = TARGET_BASIN_LEVEL - current_level
    if level_error <= 0:
        return 5.0, "🟢 목표 수위 도달 (최소 유지 유량 5%)"
    
    valve_pct = min(100.0, max(0.0, level_error * 250.0))
    return round(valve_pct, 1), f"🔵 수위 유지를 위해 밸브 {round(valve_pct, 1)}% 개방"

# -----------------------------------------------------------------------------
# Streamlit UI 레이아웃
# -----------------------------------------------------------------------------
st.title("⚛️ 하나로(HANARO) 2차 냉각계통 스마트 최적 제어 시뮬레이터")
st.caption("안전 상한선(32.0℃) 및 수위 한계(3.9m) 조건을 엄격히 지키며 팬 가동을 최소화합니다.")

st.sidebar.header("🎛️ 실시간 상태 제어판 (Input)")

# 원자로 열출력 옵션 수정 (27MW 포함)
input_power = st.sidebar.select_slider(
    "원자로 열출력 (MW)", 
    options=[0, 10, 20, 27, 30], 
    value=27,
    help="하나로의 정격 출력(30MW) 및 주요 운전 출력 level(27MW 등) 설정"
)

input_temp = st.sidebar.slider("열교환기 2차측 입구 온도 (℃)", 25.0, 33.0, 29.5, 0.1)
input_temp_rate = st.sidebar.slider("온도 변화율 (℃/min)", -0.5, 0.5, 0.05, 0.01)
input_level = st.sidebar.slider("수조(Basin) 수위 (m)", 3.00, 4.00, 3.68, 0.01)

# 계산 수행
fan_info = calculate_optimal_fans(input_temp, input_temp_rate)
valve_pct, valve_msg = calculate_makeup_valve(input_level)
margin_left = round(MARGIN_TEMP - input_temp, 2)

# 기록 저장 버튼 기능
st.sidebar.divider()
if st.sidebar.button("💾 현재 상태/결과값 기록 저장"):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_data = {
        '시각': now_str,
        '열출력(MW)': input_power,
        '입구온도(℃)': input_temp,
        '온도변화율(℃/min)': input_temp_rate,
        '수조수위(m)': input_level,
        '추천팬가동': f"{fan_info['active_fans']}대",
        '팬속도': fan_info['speed'],
        '보급수밸브(%)': valve_pct,
        '상태': fan_info['status']
    }
    st.session_state.history_log = pd.concat([st.session_state.history_log, pd.DataFrame([new_data])], ignore_index=True)
    st.sidebar.success("기록이 성공적으로 추가되었습니다!")

# KPI 카드 배치
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="열교환기 입구 온도",
        value=f"{input_temp} ℃",
        delta=f"마진까지 {margin_left} ℃",
        delta_color="inverse" if margin_left < 1.0 else "normal"
    )

with col2:
    st.metric(
        label=f"추천 팬 가동 ({input_power}MW)",
        value=f"{fan_info['active_fans']} 대 [{fan_info['speed']}]",
        delta=f"상태: {fan_info['status']}"
    )

with col3:
    st.metric(
        label="수조 수위",
        value=f"{input_level} m",
        delta=f"한계(3.9m) 차이: {round(MAX_BASIN_LEVEL - input_level, 2)} m",
        delta_color="inverse" if input_level >= 3.85 else "normal"
    )

with col4:
    st.metric(
        label="보급수 밸브 개도율",
        value=f"{valve_pct} %"
    )

st.divider()

# 메인 분석 화면 (2열 구성)
left_col, right_col = st.columns([1, 1])

with left_col:
    st.subheader("💡 AI 가이던스 및 제어 지침")
    st.markdown(f"""
    <div style="padding: 15px; border-radius: 10px; background-color: #f0f2f6; border-left: 5px solid {fan_info['color']};">
        <h4>{fan_info['msg']}</h4>
        <p><b>원자로 출력 상태:</b> {input_power} MW</p>
        <p><b>보급수 제어:</b> {valve_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.write("#### 🌀 각 팬(1~4호기) 상태 시각화")
    f1, f2, f3, f4 = st.columns(4)
    speed_labels = {0: "OFF ⚪", 1: "저속 🟢", 2: "고속 🔴"}
    
    f1.info(f"**팬 1호기**\n\n{speed_labels[fan_info['states'][0]]}")
    f2.info(f"**팬 2호기**\n\n{speed_labels[fan_info['states'][1]]}")
    f3.info(f"**팬 3호기**\n\n{speed_labels[fan_info['states'][2]]}")
    f4.info(f"**팬 4호기**\n\n{speed_labels[fan_info['states'][3]]}")

with right_col:
    st.subheader("📊 온도 마진 & 수위 제한 트래킹")
    
    # 게이지 차트 생성 (Plotly)
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = input_temp,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': f"2차측 입구 온도 (마진: 32.0℃ / 출력: {input_power}MW)"},
        gauge = {
            'axis': {'range': [25, 34]},
            'bar': {'color': fan_info['color']},
            'steps': [
                {'range': [25, 29], 'color': "lightgreen"},
                {'range': [29, 30.5], 'color': "khaki"},
                {'range': [30.5, 32], 'color': "orange"},
                {'range': [32, 34], 'color': "salmon"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 32.0
            }
        }
    ))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# -----------------------------------------------------------------------------
# 히스토리 저장 로그 표 및 다운로드 영역
# -----------------------------------------------------------------------------
st.subheader("📋 입력 및 측정 데이터 기록 (히스토리 로그)")

if not st.session_state.history_log.empty:
    st.dataframe(st.session_state.history_log, use_container_width=True)
    
    # CSV 다운로드 기능 제공
    csv_data = st.session_state.history_log.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 누적 데이터 CSV 다운로드",
        data=csv_data,
        file_name=f"hanaro_cooling_log_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )
    
    # 저장된 기록으로 트렌드 그래프 출력
    st.write("#### 📈 기록된 데이터의 온도 및 수위 추이")
    chart_df = st.session_state.history_log.copy()
    chart_df['32℃ 안전마진'] = 32.0
    st.line_chart(chart_df.set_index('시각')[['입구온도(℃)', '32℃ 안전마진', '수조수위(m)']])
else:
    st.info("왼쪽 사이드바에서 [💾 현재 상태/결과값 기록 저장] 버튼을 누르면 입력 데이터와 제어 결과가 차곡차곡 기록됩니다.")
