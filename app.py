import io

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import urllib3

# ----------------------------------------------------------------------------
# 基本設定
# ----------------------------------------------------------------------------
st.set_page_config(page_title="TWSE 開放資料分析", page_icon="📊", layout="wide")

DEFAULT_URL = "https://data.tainan.gov.tw/File/ResourceCsvDownload/24b8d897-7971-45f9-8489-b4918ee41ed7"  # 換連結
# 欄位名稱含這些字時，視為「代號/識別/日期」類欄位，不轉成數值
ID_HINTS = ("代號", "代碼", "編號", "電話", "統一", "日期", "年度", "地址", "code", "id")


# ----------------------------------------------------------------------------
# 資料讀取與清理
# ----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="下載資料中…")
def load_data(url: str, verify_ssl: bool) -> pd.DataFrame:
    """對應原本的 requests.get + read_csv(encoding='utf-8-sig')"""
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(url, verify=verify_ssl, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(io.BytesIO(response.content), encoding="utf-8-sig")  # 繁體中文
    df.columns = [str(c).strip() for c in df.columns]
    return df


def auto_convert(df: pd.DataFrame) -> pd.DataFrame:
    """把看起來像數字的文字欄位（含千分位、%）轉成數值。"""
    df = df.copy()
    for col in df.select_dtypes(include="object").columns:
        if any(h in col.lower() for h in ID_HINTS):
            continue
        cleaned = (
            df[col].astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        converted = pd.to_numeric(cleaned, errors="coerce")
        non_null = df[col].notna().sum()
        if non_null and converted.notna().sum() / non_null >= 0.9:
            df[col] = converted
    return df


def split_columns(df: pd.DataFrame):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in df.columns if c not in num_cols]
    return num_cols, cat_cols


# ----------------------------------------------------------------------------
# 側邊欄：資料來源與篩選
# ----------------------------------------------------------------------------
st.title("📊 TWSE 開放資料視覺化分析")

with st.sidebar:
    st.header("⚙️ 資料設定")
    url = st.text_input("CSV 連結", DEFAULT_URL)
    verify_ssl = st.checkbox("驗證 SSL 憑證", value=False,
                             help="原程式使用 verify=False，若來源憑證正常可勾選。")
    na_mode = st.radio(
        "缺值處理",
        ["刪除含缺值的列（同原程式 dropna）", "只刪除整列皆為空", "不處理"],
        index=0,
    )
    if st.button("🔄 重新下載資料"):
        st.cache_data.clear()

try:
    raw = load_data(url, verify_ssl)
except Exception as e:
    st.error(f"資料下載失敗：{e}")
    st.stop()

df = auto_convert(raw)
if na_mode.startswith("刪除含缺值"):
    df = df.dropna()
elif na_mode.startswith("只刪除"):
    df = df.dropna(how="all")

if df.empty:
    st.warning("清理後沒有資料，請改用較寬鬆的缺值處理方式。")
    st.stop()

num_cols, cat_cols = split_columns(df)

with st.sidebar:
    st.header("🔍 篩選")
    keyword = st.text_input("關鍵字搜尋（全欄位）")
    filter_col = st.selectbox("類別篩選欄位", ["（不篩選）"] + [
        c for c in cat_cols if df[c].nunique() <= 200
    ])
    if filter_col != "（不篩選）":
        options = sorted(df[filter_col].dropna().astype(str).unique())
        picked = st.multiselect(f"選擇 {filter_col}", options)
    else:
        picked = []

view = df.copy()
if keyword:
    mask = view.astype(str).apply(
        lambda s: s.str.contains(keyword, case=False, regex=False)
    ).any(axis=1)
    view = view[mask]
if filter_col != "（不篩選）" and picked:
    view = view[view[filter_col].astype(str).isin(picked)]

if view.empty:
    st.warning("篩選後沒有資料。")
    st.stop()

num_cols, cat_cols = split_columns(view)

# ----------------------------------------------------------------------------
# 頂部指標
# ----------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("資料筆數", f"{len(view):,}")
c2.metric("欄位數", len(view.columns))
c3.metric("數值欄位", len(num_cols))
c4.metric("類別欄位", len(cat_cols))

tab_overview, tab_uni, tab_bi, tab_corr, tab_rank = st.tabs(
    ["📋 資料總覽", "📈 單變數分析", "🔗 雙變數分析", "🧮 相關性", "🏆 排行榜"]
)

# ----------------------------------------------------------------------------
# 1. 資料總覽
# ----------------------------------------------------------------------------
with tab_overview:
    st.dataframe(view, use_container_width=True, height=420)
    st.download_button(
        "⬇️ 下載目前資料 (CSV)",
        view.to_csv(index=False).encode("utf-8-sig"),
        file_name="data01.csv",
        mime="text/csv",
    )
    left, right = st.columns(2)
    with left:
        st.subheader("欄位資訊")
        info = pd.DataFrame({
            "型態": view.dtypes.astype(str),
            "非空值數": view.notna().sum(),
            "相異值數": view.nunique(),
        })
        st.dataframe(info, use_container_width=True)
    with right:
        st.subheader("數值欄位統計")
        if num_cols:
            st.dataframe(view[num_cols].describe().T, use_container_width=True)
        else:
            st.info("沒有偵測到數值欄位。")

# ----------------------------------------------------------------------------
# 2. 單變數分析
# ----------------------------------------------------------------------------
with tab_uni:
    col = st.selectbox("選擇欄位", view.columns.tolist(), key="uni_col")
    if col in num_cols:
        bins = st.slider("直方圖分組數", 5, 100, 30)
        a, b = st.columns(2)
        a.plotly_chart(
            px.histogram(view, x=col, nbins=bins, title=f"{col} 分佈"),
            use_container_width=True,
        )
        b.plotly_chart(
            px.box(view, y=col, points="outliers", title=f"{col} 箱型圖"),
            use_container_width=True,
        )
    else:
        top_n = st.slider("顯示前 N 類", 5, 50, 15)
        vc = view[col].astype(str).value_counts().head(top_n).reset_index()
        vc.columns = [col, "數量"]
        a, b = st.columns(2)
        a.plotly_chart(
            px.bar(vc, x=col, y="數量", text="數量", title=f"{col} 次數分佈"),
            use_container_width=True,
        )
        if view[col].nunique() <= 12:
            b.plotly_chart(
                px.pie(vc, names=col, values="數量", title=f"{col} 占比"),
                use_container_width=True,
            )
        else:
            b.info("相異值超過 12 種，不顯示圓餅圖。")

# ----------------------------------------------------------------------------
# 3. 雙變數分析
# ----------------------------------------------------------------------------
with tab_bi:
    x = st.selectbox("X 軸", view.columns.tolist(), key="bi_x")
    y_options = [c for c in view.columns if c != x]
    y = st.selectbox("Y 軸", y_options, key="bi_y") if y_options else None

    if y is None:
        st.info("需要至少兩個欄位。")
    elif x in num_cols and y in num_cols:
        color_opts = ["（無）"] + [c for c in cat_cols if view[c].nunique() <= 20]
        color = st.selectbox("顏色分組", color_opts)
        fig = px.scatter(
            view, x=x, y=y,
            color=None if color == "（無）" else color,
            hover_data=view.columns[:6].tolist(),
            title=f"{x} vs {y}",
        )
        st.plotly_chart(fig, use_container_width=True)
    elif (x in cat_cols) != (y in cat_cols):  # 一個類別、一個數值
        cat, num = (x, y) if x in cat_cols else (y, x)
        agg = st.radio("彙總方式", ["mean", "sum", "median", "count"], horizontal=True)
        top_n = st.slider("顯示前 N 類", 5, 50, 15, key="bi_topn")
        g = (view.groupby(cat)[num].agg(agg)
             .sort_values(ascending=False).head(top_n).reset_index())
        st.plotly_chart(
            px.bar(g, x=cat, y=num, text_auto=".3s", title=f"{cat} 的 {num}（{agg}）"),
            use_container_width=True,
        )
        st.plotly_chart(
            px.box(view[view[cat].isin(g[cat])], x=cat, y=num, title=f"{cat} 的 {num} 分佈"),
            use_container_width=True,
        )
    else:  # 兩個類別
        top_x = view[x].astype(str).value_counts().head(15).index
        top_y = view[y].astype(str).value_counts().head(15).index
        sub = view[view[x].astype(str).isin(top_x) & view[y].astype(str).isin(top_y)]
        ct = pd.crosstab(sub[y].astype(str), sub[x].astype(str))
        st.plotly_chart(
            px.imshow(ct, text_auto=True, aspect="auto",
                      title=f"{x} × {y} 交叉表（各取前 15 類）"),
            use_container_width=True,
        )

# ----------------------------------------------------------------------------
# 4. 相關性
# ----------------------------------------------------------------------------
with tab_corr:
    if len(num_cols) < 2:
        st.info("需要至少兩個數值欄位才能計算相關性。")
    else:
        chosen = st.multiselect("選擇欄位", num_cols, default=num_cols[:12])
        if len(chosen) >= 2:
            corr = view[chosen].corr()
            st.plotly_chart(
                px.imshow(corr, text_auto=".2f", zmin=-1, zmax=1,
                          color_continuous_scale="RdBu_r", aspect="auto",
                          title="相關係數矩陣"),
                use_container_width=True,
            )
        else:
            st.info("請至少選擇兩個欄位。")

# ----------------------------------------------------------------------------
# 5. 排行榜
# ----------------------------------------------------------------------------
with tab_rank:
    if not num_cols:
        st.info("沒有偵測到數值欄位。")
    else:
        a, b, c = st.columns(3)
        metric = a.selectbox("排序欄位（數值）", num_cols)
        label = b.selectbox("標籤欄位", cat_cols if cat_cols else view.columns.tolist())
        n = c.slider("顯示筆數", 5, 50, 10)
        asc = st.checkbox("由小到大")
        rank = view.sort_values(metric, ascending=asc).head(n)
        fig = px.bar(
            rank.iloc[::-1], x=metric, y=label, orientation="h",
            text_auto=".3s", title=f"{metric} {'最小' if asc else '最大'} Top {n}",
        )
        fig.update_yaxes(type="category")
        st.plotly_chart(fig, use_container_width=True)
