import io
import re

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================
st.set_page_config(
    page_title="전국 유소년 인구 지도",
    page_icon="🗺️",
    layout="wide",
)

# 인구 데이터 주소
POP_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

# 시군구 경계 데이터 주소
GEO_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)


# =========================================================
# 2. 성별별 지도 색상
# =========================================================

# 전체 / 남자 / 여자를 선택할 때
# 지도 색상도 함께 바뀌도록 설정한다.
COLOR_PALETTES = {

    # 전체 - 청록 계열
    "전체": [
        "#ECFDF5",
        "#A7F3D0",
        "#5EEAD4",
        "#14B8A6",
        "#0F766E",
    ],

    # 남자 - 파란 계열
    "남자": [
        "#EFF6FF",
        "#BFDBFE",
        "#93C5FD",
        "#3B82F6",
        "#1D4ED8",
    ],

    # 여자 - 로즈 계열
    "여자": [
        "#FFF1F2",
        "#FECDD3",
        "#FDA4AF",
        "#F43F5E",
        "#BE123C",
    ],
}


def make_step_colorscale(colors):
    """
    Plotly는 기본적으로 색을 부드럽게 이어서 표현한다.
    같은 색을 구간 양 끝에 반복해서 넣어
    5단계로 딱 끊어지는 단계구분도를 만든다.
    """

    return [
        [0.00, colors[0]],
        [0.20, colors[0]],

        [0.20, colors[1]],
        [0.40, colors[1]],

        [0.40, colors[2]],
        [0.60, colors[2]],

        [0.60, colors[3]],
        [0.80, colors[3]],

        [0.80, colors[4]],
        [1.00, colors[4]],
    ]


# =========================================================
# 3. 파일 다운로드
# =========================================================
@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def download_bytes(url):
    """
    인터넷에서 파일을 내려받는다.

    캐시를 사용해서 매번 다시 다운로드하지 않도록 한다.
    """

    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
    )

    response.raise_for_status()

    return response.content


# =========================================================
# 4. CSV 인코딩 확인
# =========================================================
def detect_csv_encoding(data):
    """
    CSV 파일이 UTF-8인지 CP949인지 확인한다.
    """

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp949",
    ]

    for encoding in encodings:

        try:
            pd.read_csv(
                io.BytesIO(data),
                compression="gzip",
                nrows=0,
                encoding=encoding,
            )

            return encoding

        except UnicodeDecodeError:
            continue

    raise ValueError(
        "CSV 파일의 문자 인코딩을 확인할 수 없습니다."
    )


# =========================================================
# 5. 나이 열에서 나이 숫자 추출
# =========================================================
def age_from_column(column_name, prefix):
    """
    예시

    계_0세 -> 0
    남_14세 -> 14
    여_65세 -> 65
    계_100세 이상 -> 100
    """

    name = str(column_name).strip()

    if name == f"{prefix}_100세 이상":
        return 100

    match = re.fullmatch(
        rf"{prefix}_(\d+)세",
        name,
    )

    if match:
        return int(match.group(1))

    return None


# =========================================================
# 6. 인구 데이터 처리
# =========================================================
@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_population(url):
    """
    가장 최신 연도의 읍면동 자료를 불러온 뒤
    시군구 코드 앞 5자리 기준으로 합친다.

    유소년 인구는 0~14세로 계산한다.
    """

    raw = download_bytes(url)

    encoding = detect_csv_encoding(raw)


    # -----------------------------------------------------
    # 열 이름만 먼저 읽기
    # -----------------------------------------------------
    header = pd.read_csv(
        io.BytesIO(raw),
        compression="gzip",
        nrows=0,
        encoding=encoding,
    )

    columns = list(header.columns)


    # -----------------------------------------------------
    # 전체 / 남자 / 여자 나이 열 찾기
    # -----------------------------------------------------
    total_age_columns = []
    male_age_columns = []
    female_age_columns = []


    for column in columns:

        if age_from_column(column, "계") is not None:
            total_age_columns.append(column)

        if age_from_column(column, "남") is not None:
            male_age_columns.append(column)

        if age_from_column(column, "여") is not None:
            female_age_columns.append(column)


    # -----------------------------------------------------
    # 유소년 인구 = 0~14세
    # -----------------------------------------------------
    youth_total_columns = [
        column
        for column in total_age_columns
        if 0 <= age_from_column(column, "계") <= 14
    ]

    youth_male_columns = [
        column
        for column in male_age_columns
        if 0 <= age_from_column(column, "남") <= 14
    ]

    youth_female_columns = [
        column
        for column in female_age_columns
        if 0 <= age_from_column(column, "여") <= 14
    ]


    if not youth_total_columns:
        raise ValueError(
            "0~14세 전체 인구 열을 찾지 못했습니다."
        )

    if not youth_male_columns:
        raise ValueError(
            "0~14세 남자 인구 열을 찾지 못했습니다."
        )

    if not youth_female_columns:
        raise ValueError(
            "0~14세 여자 인구 열을 찾지 못했습니다."
        )


    # -----------------------------------------------------
    # 가장 최신 연도 찾기
    # -----------------------------------------------------
    years = pd.read_csv(
        io.BytesIO(raw),
        compression="gzip",
        usecols=["연도"],
        encoding=encoding,
    )["연도"]

    years = pd.to_numeric(
        years,
        errors="coerce",
    )

    latest_year = int(
        years.max()
    )


    # -----------------------------------------------------
    # 계산에 필요한 열만 읽기
    # -----------------------------------------------------
    age_columns = (
        total_age_columns
        + male_age_columns
        + female_age_columns
    )

    use_columns = [
        "연도",
        "시도",
        "시군구",
        "동",
        "코드",
    ] + age_columns


    # 코드 열은 반드시 문자열로 읽는다.
    # 행정동 코드는 숫자가 아니라 지역 식별용 이름표다.
    reader = pd.read_csv(
        io.BytesIO(raw),
        compression="gzip",
        usecols=use_columns,
        dtype={
            "코드": "string"
        },
        encoding=encoding,
        chunksize=5000,
        low_memory=False,
    )


    latest_chunks = []


    # -----------------------------------------------------
    # 최신 연도만 남기기
    # -----------------------------------------------------
    for chunk in reader:

        year_values = pd.to_numeric(
            chunk["연도"],
            errors="coerce",
        )

        selected = chunk.loc[
            year_values.eq(latest_year)
        ].copy()

        if not selected.empty:
            latest_chunks.append(selected)


    if not latest_chunks:
        raise ValueError(
            f"{latest_year}년 자료를 찾지 못했습니다."
        )


    latest = pd.concat(
        latest_chunks,
        ignore_index=True,
    )


    # -----------------------------------------------------
    # 읍면동 자료만 사용
    # -----------------------------------------------------
    latest["동"] = (
        latest["동"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    latest = latest.loc[
        latest["동"].ne("")
    ].copy()


    # -----------------------------------------------------
    # 코드 정리
    # -----------------------------------------------------
    latest["코드"] = (
        latest["코드"]
        .astype("string")
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
    )


    # 행정동 코드 앞 5자리가 시군구 코드
    latest["시군구코드"] = (
        latest["코드"]
        .str[:5]
    )


    # -----------------------------------------------------
    # 인구 데이터를 숫자로 변환
    # -----------------------------------------------------
    latest[age_columns] = (
        latest[age_columns]
        .replace(
            {",": ""},
            regex=True,
        )
        .apply(
            pd.to_numeric,
            errors="coerce",
        )
        .fillna(0)
    )


    # =====================================================
    # 전체
    # =====================================================
    latest["전체_총인구"] = (
        latest[total_age_columns]
        .sum(axis=1)
    )

    latest["전체_유소년인구"] = (
        latest[youth_total_columns]
        .sum(axis=1)
    )


    # =====================================================
    # 남자
    # =====================================================
    latest["남자_총인구"] = (
        latest[male_age_columns]
        .sum(axis=1)
    )

    latest["남자_유소년인구"] = (
        latest[youth_male_columns]
        .sum(axis=1)
    )


    # =====================================================
    # 여자
    # =====================================================
    latest["여자_총인구"] = (
        latest[female_age_columns]
        .sum(axis=1)
    )

    latest["여자_유소년인구"] = (
        latest[youth_female_columns]
        .sum(axis=1)
    )


    # -----------------------------------------------------
    # 읍면동을 시군구별로 합치기
    # -----------------------------------------------------
    sigungu = (
        latest
        .groupby(
            "시군구코드",
            as_index=False,
        )
        [
            [
                "전체_총인구",
                "전체_유소년인구",
                "남자_총인구",
                "남자_유소년인구",
                "여자_총인구",
                "여자_유소년인구",
            ]
        ]
        .sum()
    )


    # -----------------------------------------------------
    # 유소년 인구 비율 계산
    # -----------------------------------------------------

    # 전체 유소년 비율
    sigungu["전체_유소년비율"] = (
        sigungu["전체_유소년인구"]
        / sigungu["전체_총인구"]
        * 100
    )

    # 남자 중 유소년 비율
    sigungu["남자_유소년비율"] = (
        sigungu["남자_유소년인구"]
        / sigungu["남자_총인구"]
        * 100
    )

    # 여자 중 유소년 비율
    sigungu["여자_유소년비율"] = (
        sigungu["여자_유소년인구"]
        / sigungu["여자_총인구"]
        * 100
    )


    return latest_year, sigungu


# =========================================================
# 7. GeoJSON 불러오기
# =========================================================
@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_geojson(url):
    """
    전국 시군구 경계 GeoJSON을 불러온다.
    """

    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
    )

    response.raise_for_status()

    geojson = response.json()


    boundary_rows = []


    for feature in geojson.get(
        "features",
        [],
    ):

        properties = feature.get(
            "properties",
            {},
        )


        raw_code = properties.get(
            "코드"
        )


        if raw_code is None:
            continue


        code = str(
            raw_code
        ).strip()


        code = code.replace(
            ".0",
            "",
        )

        code = code.zfill(5)


        # GeoJSON 코드도 문자열로 통일한다.
        properties["코드"] = code


        boundary_rows.append(
            {
                "시군구코드": code,

                "시군구": properties.get(
                    "시군구",
                    "",
                ),

                "시도": properties.get(
                    "시도",
                    "",
                ),
            }
        )


    boundaries = pd.DataFrame(
        boundary_rows
    )


    boundaries = (
        boundaries
        .drop_duplicates(
            "시군구코드"
        )
    )


    return geojson, boundaries


# =========================================================
# 8. 제목
# =========================================================
st.title(
    "전국 유소년 인구 지도"
)

st.caption(
    "전국 시군구별 0~14세 유소년 인구 비율을 "
    "지도에서 확인할 수 있습니다."
)


# =========================================================
# 9. 데이터 불러오기
# =========================================================
try:

    with st.spinner(
        "최신 인구 자료와 지도 경계를 불러오는 중입니다..."
    ):

        latest_year, population = (
            load_population(
                POP_URL
            )
        )

        geojson, boundaries = (
            load_geojson(
                GEO_URL
            )
        )


except Exception as e:

    st.error(
        "데이터를 불러오는 중 "
        f"오류가 발생했습니다: {e}"
    )

    st.stop()


# =========================================================
# 10. 성별 선택
# =========================================================
st.subheader(
    "조회 조건"
)

gender = st.radio(
    "성별",
    [
        "전체",
        "남자",
        "여자",
    ],
    horizontal=True,
)


# ---------------------------------------------------------
# 선택한 성별에 따라 사용할 열 결정
# ---------------------------------------------------------
if gender == "전체":

    rate_column = "전체_유소년비율"
    youth_column = "전체_유소년인구"
    population_column = "전체_총인구"

elif gender == "남자":

    rate_column = "남자_유소년비율"
    youth_column = "남자_유소년인구"
    population_column = "남자_총인구"

else:

    rate_column = "여자_유소년비율"
    youth_column = "여자_유소년인구"
    population_column = "여자_총인구"


# ---------------------------------------------------------
# 선택한 성별에 따라 지도 색상 변경
# ---------------------------------------------------------
selected_colors = COLOR_PALETTES[
    gender
]

STEP_COLORSCALE = (
    make_step_colorscale(
        selected_colors
    )
)


# =========================================================
# 11. 지도 경계와 인구 데이터 연결
# =========================================================

# 이름이 아니라 시군구 5자리 코드로 연결한다.
map_data = boundaries.merge(
    population,
    on="시군구코드",
    how="left",
)


# 선택한 성별의 값을 공통 열 이름으로 만든다.
map_data["유소년비율"] = (
    map_data[rate_column]
)

map_data["유소년인구"] = (
    map_data[youth_column]
)

map_data["총인구"] = (
    map_data[population_column]
)


# =========================================================
# 12. 유소년 비율을 5단계로 분류
# =========================================================

valid_values = (
    map_data[
        "유소년비율"
    ]
    .dropna()
)


# 전국 시군구를 실제 값 기준으로
# 다섯 덩어리로 나눈다.
q20 = valid_values.quantile(0.2)
q40 = valid_values.quantile(0.4)
q60 = valid_values.quantile(0.6)
q80 = valid_values.quantile(0.8)


BIN_EDGES = [
    float("-inf"),
    q20,
    q40,
    q60,
    q80,
    float("inf"),
]


BIN_LABELS = [
    f"{q20:.1f}% 미만",

    (
        f"{q20:.1f}% 이상 ~ "
        f"{q40:.1f}% 미만"
    ),

    (
        f"{q40:.1f}% 이상 ~ "
        f"{q60:.1f}% 미만"
    ),

    (
        f"{q60:.1f}% 이상 ~ "
        f"{q80:.1f}% 미만"
    ),

    f"{q80:.1f}% 이상",
]


map_data["구간"] = pd.cut(
    map_data["유소년비율"],
    bins=BIN_EDGES,
    labels=BIN_LABELS,
    right=False,
    include_lowest=True,
)


# Plotly에서 색을 나누기 위한 숫자
label_to_value = {
    label: i + 0.5
    for i, label in enumerate(
        BIN_LABELS
    )
}


map_data["등급값"] = (
    map_data["구간"]
    .map(label_to_value)
    .astype(float)
)


# =========================================================
# 13. 지도 제목
# =========================================================
st.subheader(
    f"{latest_year}년 시군구별 유소년 인구 비율"
)

st.caption(
    f"현재 선택: {gender} · 유소년 인구 기준: 만 0~14세"
)


# =========================================================
# 14. 지도 만들기
# =========================================================
fig = go.Figure()


mapped = map_data.dropna(
    subset=[
        "유소년비율",
        "등급값",
    ]
).copy()


fig.add_trace(
    go.Choropleth(

        # 지도 경계
        geojson=geojson,

        # GeoJSON 안의 시군구 코드
        featureidkey=(
            "properties.코드"
        ),

        # 인구 데이터의 시군구 코드
        locations=mapped[
            "시군구코드"
        ],

        # 5단계 색상용 값
        z=mapped[
            "등급값"
        ],

        zmin=0,
        zmax=5,

        colorscale=(
            STEP_COLORSCALE
        ),


        # 시군구 경계선
        marker_line_color=(
            "#FFFFFF"
        ),

        marker_line_width=0.7,


        # 마우스 올렸을 때 사용할 정보
        customdata=mapped[
            [
                "시도",
                "시군구",
                "유소년비율",
                "유소년인구",
                "총인구",
            ]
        ].to_numpy(),


        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "시도: %{customdata[0]}<br>"
            f"성별: {gender}<br>"
            "유소년 비율: %{customdata[2]:.1f}%<br>"
            "유소년 인구: %{customdata[3]:,.0f}명"
            "<extra></extra>"
        ),


        # 오른쪽 범례
        colorbar=dict(

            title="유소년 비율",

            tickmode="array",

            tickvals=[
                0.5,
                1.5,
                2.5,
                3.5,
                4.5,
            ],

            ticktext=(
                BIN_LABELS
            ),

            thickness=18,

            len=0.68,

            x=1.01,
        ),
    )
)


# =========================================================
# 15. 데이터 없는 지역
# =========================================================
missing = map_data.loc[
    map_data[
        "유소년비율"
    ].isna()
].copy()


if not missing.empty:

    fig.add_trace(
        go.Choropleth(

            geojson=geojson,

            featureidkey=(
                "properties.코드"
            ),

            locations=missing[
                "시군구코드"
            ],

            z=[
                1
            ] * len(missing),

            # 자료가 없는 곳은 회색
            colorscale=[
                [0, "#E5E7EB"],
                [1, "#E5E7EB"],
            ],

            showscale=False,

            marker_line_color=(
                "#FFFFFF"
            ),

            marker_line_width=0.7,


            customdata=missing[
                [
                    "시도",
                    "시군구",
                ]
            ].to_numpy(),


            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "시도: %{customdata[0]}<br>"
                "자료 없음"
                "<extra></extra>"
            ),
        )
    )


# =========================================================
# 16. 배경 지도 제거
# =========================================================
fig.update_geos(

    # 대한민국 전체가 화면에 맞도록 설정
    fitbounds="locations",

    # 배경 지도 요소 제거
    visible=False,

    showcoastlines=False,
    showcountries=False,
    showland=False,
    showocean=False,
    showlakes=False,
    showrivers=False,
    showframe=False,

    bgcolor="rgba(0,0,0,0)",
)


fig.update_layout(

    height=760,

    margin=dict(
        l=0,
        r=130,
        t=10,
        b=0,
    ),

    paper_bgcolor=(
        "rgba(0,0,0,0)"
    ),

    plot_bgcolor=(
        "rgba(0,0,0,0)"
    ),

    hoverlabel=dict(
        namelength=-1
    ),
)


# =========================================================
# 17. 지도 출력
# =========================================================
st.plotly_chart(
    fig,
    use_container_width=True,

    config={
        "displayModeBar": False
    },
)


# =========================================================
# 18. 유소년 비율 높은 곳 / 낮은 곳
# =========================================================
ranking = (
    map_data
    .dropna(
        subset=[
            "유소년비율"
        ]
    )
    [
        [
            "시도",
            "시군구",
            "유소년비율",
            "유소년인구",
        ]
    ]
    .copy()
)


# 유소년 비율 높은 곳 10개
high10 = (
    ranking
    .sort_values(
        "유소년비율",
        ascending=False,
    )
    .head(10)
    .reset_index(
        drop=True
    )
)


# 유소년 비율 낮은 곳 10개
low10 = (
    ranking
    .sort_values(
        "유소년비율",
        ascending=True,
    )
    .head(10)
    .reset_index(
        drop=True
    )
)


# 순위 추가
high10.insert(
    0,
    "순위",
    range(
        1,
        len(high10) + 1,
    ),
)

low10.insert(
    0,
    "순위",
    range(
        1,
        len(low10) + 1,
    ),
)


# =========================================================
# 19. 표 두 개 나란히 표시
# =========================================================
left, right = st.columns(2)


with left:

    st.subheader(
        f"유소년 비율 높은 곳 10개 · {gender}"
    )

    st.dataframe(
        high10,

        hide_index=True,

        use_container_width=True,

        column_config={

            "유소년비율":
                st.column_config.NumberColumn(
                    "유소년 비율",
                    format="%.1f%%",
                ),

            "유소년인구":
                st.column_config.NumberColumn(
                    "유소년 인구",
                    format="%d명",
                ),
        },
    )


with right:

    st.subheader(
        f"유소년 비율 낮은 곳 10개 · {gender}"
    )

    st.dataframe(
        low10,

        hide_index=True,

        use_container_width=True,

        column_config={

            "유소년비율":
                st.column_config.NumberColumn(
                    "유소년 비율",
                    format="%.1f%%",
                ),

            "유소년인구":
                st.column_config.NumberColumn(
                    "유소년 인구",
                    format="%d명",
                ),
        },
    )
