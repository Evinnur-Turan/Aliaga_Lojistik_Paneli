"""
Aliağa Lojistik & Tedarik Zinciri Tahmin Paneli
================================================
Aliağa (İzmir) sanayi ve liman bölgesi için SENTETİK verilerle çalışan,
tahmin yapan ve Streamlit üzerinde harita + grafik gösteren demo uygulama.

Çalıştırma:
    pip install streamlit pandas numpy plotly pydeck
    streamlit run aliaga_lojistik_paneli.py

Not: Tüm veriler rastgele üretilmiştir; terminal koordinatları yaklaşık/temsilidir.
Gerçek verilerle (AIS, liman istatistikleri, ERP) çalışmak için sadece
`generate_data()` fonksiyonunu kendi veri kaynağınızla değiştirmeniz yeterlidir.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="Aliağa Lojistik Paneli", page_icon="🚢", layout="wide")

# --------------------------------------------------------------------------- #
# 1) SABİTLER: terminaller, ürünler, rotalar
# --------------------------------------------------------------------------- #
ALIAGA_CENTER = (38.80, 26.93)  # lat, lon (yaklaşık)

# Ürün parametreleri: yön, ortalama gemi parti büyüklüğü (ton), mevsimsel genlik,
# mevsim zirvesi (yılın günü), hafta sonu düşüşü, yıllık büyüme
PRODUCTS = {
    "Ham Petrol":     dict(dir="Giriş", parcel=100_000, amp=0.05, peak=200, wkend=0.00, growth=0.03),
    "Rafine Ürünler": dict(dir="Çıkış", parcel=30_000,  amp=0.10, peak=200, wkend=0.05, growth=0.02),
    "Petrokimya":     dict(dir="Çıkış", parcel=8_000,   amp=0.06, peak=150, wkend=0.20, growth=0.05),
    "LNG":            dict(dir="Giriş", parcel=70_000,  amp=0.25, peak=20,  wkend=0.00, growth=0.06),
    "Çelik & Metal":  dict(dir="Çıkış", parcel=12_000,  amp=0.08, peak=120, wkend=0.25, growth=0.01),
    "Dökme Kuru Yük": dict(dir="Giriş", parcel=35_000,  amp=0.10, peak=280, wkend=0.15, growth=0.02),
}

# Terminal: konum (temsili), rıhtım sayısı, günlük ortalama ton (ürün bazında)
TERMINALS = {
    "Tüpraş İskeleleri":  dict(lat=38.7960, lon=26.9120, berths=3,
                               products={"Ham Petrol": 30_000, "Rafine Ürünler": 28_000}),
    "Petkim Limanı":      dict(lat=38.8250, lon=26.9050, berths=2,
                               products={"Petrokimya": 9_000, "Rafine Ürünler": 5_000}),
    "Ege Gaz LNG":        dict(lat=38.7750, lon=26.9300, berths=1,
                               products={"LNG": 12_000}),
    "Nemrut / Habaş":     dict(lat=38.7400, lon=26.9650, berths=3,
                               products={"Dökme Kuru Yük": 14_000, "Çelik & Metal": 6_000}),
    "İzdemir Limanı":     dict(lat=38.7600, lon=26.9400, berths=2,
                               products={"Çelik & Metal": 7_000, "Dökme Kuru Yük": 9_000}),
}

# Bölgesel akış rotaları: (ad, lat, lon, ürün, pay)
ROUTES = [
    ("Ceyhan", 36.88, 35.93, "Ham Petrol", 0.35),
    ("Novorossiysk", 44.72, 37.77, "Ham Petrol", 0.25),
    ("Es Sider (Libya)", 30.63, 18.35, "Ham Petrol", 0.20),
    ("Basra", 29.90, 48.80, "Ham Petrol", 0.20),
    ("Skikda (Cezayir)", 36.88, 6.90, "LNG", 0.50),
    ("Sabine Pass (ABD)", 29.74, -93.87, "LNG", 0.30),
    ("Ras Laffan (Katar)", 25.90, 51.55, "LNG", 0.20),
    ("Trieste", 45.65, 13.77, "Rafine Ürünler", 0.30),
    ("Ambarlı", 40.97, 28.69, "Rafine Ürünler", 0.40),
    ("Marsaxlokk (Malta)", 35.84, 14.54, "Rafine Ürünler", 0.30),
    ("Rotterdam", 51.95, 4.14, "Petrokimya", 0.40),
    ("Cenova", 44.41, 8.92, "Petrokimya", 0.40),
    ("Mersin", 36.80, 34.64, "Petrokimya", 0.20),
    ("İskenderiye", 31.20, 29.88, "Çelik & Metal", 0.40),
    ("Köstence", 44.17, 28.65, "Çelik & Metal", 0.30),
    ("Marsaxlokk (Malta) ", 35.84, 14.54, "Çelik & Metal", 0.30),
    ("Çornomorsk", 46.30, 30.70, "Dökme Kuru Yük", 0.40),
    ("Köstence ", 44.17, 28.65, "Dökme Kuru Yük", 0.30),
    ("Port Said", 31.26, 32.30, "Dökme Kuru Yük", 0.30),
]

BERTH_DAYS_PER_VESSEL = 1.3  # bir geminin ortalama rıhtımda kalış süresi (gün)


# --------------------------------------------------------------------------- #
# 2) SENTETİK VERİ ÜRETİMİ
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Sentetik veri üretiliyor...")
def generate_data(seed: int = 42, days: int = 730):
    """İki yıllık günlük kargo (ton) ve gemi trafiği verisi üretir."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    dates = pd.date_range(end=end, periods=days, freq="D")
    doy, wd, month = dates.dayofyear.values, dates.dayofweek.values, dates.month.values
    tt = np.arange(days) / 365.25

    cargo_rows, term_rows = [], []
    for tname, t in TERMINALS.items():
        # Kış aylarında fırtına/kapanış olasılığı daha yüksek
        storm_p = np.where(np.isin(month, [11, 12, 1, 2, 3]), 0.06, 0.015)
        storm = rng.random(days) < storm_p
        catch_up = np.r_[False, storm[:-1]]  # kapanıştan sonraki gün telafi yoğunluğu
        port_factor = np.where(storm, 0.35, np.where(catch_up, 1.18, 1.0))

        vessels_total = np.zeros(days)
        for prod, base in t["products"].items():
            p = PRODUCTS[prod]
            seasonal = 1 + p["amp"] * np.cos(2 * np.pi * (doy - p["peak"]) / 365.25)
            weekly = 1 - p["wkend"] * (wd >= 5)
            trend = 1 + p["growth"] * tt
            noise = rng.lognormal(0, 0.08, days)
            tonnes = base * seasonal * weekly * trend * noise * port_factor
            vessels = rng.poisson(tonnes / p["parcel"])
            vessels_total += vessels
            cargo_rows.append(pd.DataFrame({
                "date": dates, "terminal": tname, "product": prod,
                "direction": p["dir"], "tonnes": tonnes.round(0),
            }))

        util = vessels_total * BERTH_DAYS_PER_VESSEL / t["berths"]
        wait_h = (3 + 45 * np.maximum(0, util - 0.65) ** 1.5
                  + 14 * storm + 8 * catch_up + np.abs(rng.normal(0, 1.5, days)))
        term_rows.append(pd.DataFrame({
            "date": dates, "terminal": tname, "vessels": vessels_total.astype(int),
            "berths": t["berths"], "berth_util": util.round(3),
            "wait_h": wait_h.round(1), "weather_closure": storm,
        }))

    return pd.concat(cargo_rows, ignore_index=True), pd.concat(term_rows, ignore_index=True)


# --------------------------------------------------------------------------- #
# 3) TAHMİN MODELİ (sadece numpy: trend + haftalık/yıllık Fourier mevsimsellik)
# --------------------------------------------------------------------------- #
def _design(index: pd.DatetimeIndex, origin: pd.Timestamp) -> np.ndarray:
    t = (index - origin).days.values.astype(float)
    cols = [np.ones_like(t), t / 365.25]
    for period, order in ((7, 3), (365.25, 3)):
        for k in range(1, order + 1):
            cols += [np.sin(2 * np.pi * k * t / period), np.cos(2 * np.pi * k * t / period)]
    return np.column_stack(cols)


def _robust_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """En küçük kareler; kapanış gibi aşırı düşük günleri dışlayarak bir kez yeniden fit eder."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    keep = resid > -2.5 * resid.std()
    beta, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
    return beta


@st.cache_data(show_spinner=False)
def forecast_series(series: pd.Series, horizon: int, holdout: int = 28):
    """Günlük seri için tahmin, %95 aralık ve son `holdout` gün üzerinde MAPE döndürür."""
    y = series.values.astype(float)
    X = _design(series.index, series.index[0])

    beta_bt = _robust_fit(X[:-holdout], y[:-holdout])
    pred_bt = X[-holdout:] @ beta_bt
    mape = float(np.mean(np.abs(y[-holdout:] - pred_bt) / np.maximum(y[-holdout:], 1)) * 100)

    beta = _robust_fit(X, y)
    resid = y - X @ beta
    sigma = float(resid[resid > -2.5 * resid.std()].std())

    future_idx = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    mid = np.maximum(_design(future_idx, series.index[0]) @ beta, 0)
    widen = 1 + 0.15 * np.sqrt(np.arange(1, horizon + 1) / 30)
    lo = np.maximum(mid - 1.96 * sigma * widen, 0)
    hi = mid + 1.96 * sigma * widen
    return pd.DataFrame({"mid": mid, "lo": lo, "hi": hi}, index=future_idx), mape


def apply_scenario(df: pd.DataFrame, demand_pct: float, closure_start, closure_days: int) -> pd.DataFrame:
    """Talep şoku + liman kapanışı (kayıp hacim sonraki 7 günde telafi edilir)."""
    out = df * (1 + demand_pct / 100)
    if closure_days > 0:
        start = pd.Timestamp(closure_start)
        closed = ((out.index >= start) & (out.index < start + pd.Timedelta(days=closure_days)))
        if closed.any():
            lost = out.loc[closed].sum().values
            out.loc[closed, :] = 0.0
            after = np.where(out.index > out.index[closed][-1])[0][:7]
            if len(after):
                out.iloc[after, :] = out.iloc[after, :].values + lost / len(after)
    return out


def daily_series(df: pd.DataFrame, col: str, all_dates: pd.DatetimeIndex) -> pd.Series:
    return df.groupby("date")[col].sum().reindex(all_dates, fill_value=0.0)


def simulate_stock(inflow: np.ndarray, proc: float, cap: float, start: float) -> np.ndarray:
    s, out = start, []
    for x in inflow:
        s = min(cap, max(0.0, s + x - proc))
        out.append(s)
    return np.array(out)


def fmt(x: float, dec: int = 0) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def show(func, *args, **kwargs):
    """Streamlit sürümleri arası genişlik parametresi uyumluluğu."""
    try:
        return func(*args, width="stretch", **kwargs)
    except Exception:
        return func(*args, use_container_width=True, **kwargs)


# --------------------------------------------------------------------------- #
# 4) ARAYÜZ
# --------------------------------------------------------------------------- #
def main():
    cargo_all, term_all = generate_data()
    all_dates = pd.DatetimeIndex(sorted(cargo_all["date"].unique()))

    st.title("🚢 Aliağa Lojistik & Tedarik Zinciri Tahmin Paneli")
    st.caption("Petrokimya, rafineri, LNG ve dökme yük akışları · Sentetik veri · Tahmin: trend + mevsimsellik modeli")

    # ---- Kenar çubuğu ----
    with st.sidebar:
        st.header("Filtreler")
        sel_terms = st.multiselect("Terminaller", list(TERMINALS), default=list(TERMINALS))
        sel_prods = st.multiselect("Ürünler", list(PRODUCTS), default=list(PRODUCTS))
        window = st.select_slider("Geçmiş pencere (gün)", options=[30, 90, 180, 365], value=90)

        st.header("Tahmin & Senaryo")
        horizon = st.slider("Tahmin ufku (gün)", 14, 120, 60, step=7)
        demand_pct = st.slider("Talep şoku (%)", -30, 30, 0)
        closure_days = st.slider("Liman kapanışı (gün)", 0, 7, 0, help="Fırtına/grev gibi tam kapanış")
        closure_start = st.date_input(
            "Kapanış başlangıcı",
            value=(all_dates[-1] + pd.Timedelta(days=10)).date(),
            min_value=(all_dates[-1] + pd.Timedelta(days=1)).date(),
            max_value=(all_dates[-1] + pd.Timedelta(days=horizon)).date(),
            disabled=closure_days == 0,
        )

    if not sel_terms or not sel_prods:
        st.warning("Lütfen en az bir terminal ve bir ürün seçin.")
        st.stop()

    cargo = cargo_all[cargo_all.terminal.isin(sel_terms) & cargo_all["product"].isin(sel_prods)]
    terms = term_all[term_all.terminal.isin(sel_terms)]
    if cargo.empty:
        st.warning("Seçilen terminal/ürün kombinasyonunda veri yok (ör. Ege Gaz yalnızca LNG işler).")
        st.stop()

    end = all_dates[-1]
    cur = cargo[cargo.date > end - pd.Timedelta(days=window)]
    prev = cargo[(cargo.date <= end - pd.Timedelta(days=window)) &
                 (cargo.date > end - pd.Timedelta(days=2 * window))]
    cur_t = terms[terms.date > end - pd.Timedelta(days=window)]
    prev_t = terms[(terms.date <= end - pd.Timedelta(days=window)) &
                   (terms.date > end - pd.Timedelta(days=2 * window))]
    berths_total = sum(TERMINALS[t]["berths"] for t in sel_terms)

    # ---- Ana tahmin (seçilen filtre için toplam ton ve gemi sayısı) ----
    ton_series = daily_series(cargo, "tonnes", all_dates)
    ves_series = daily_series(terms, "vessels", all_dates)
    fc_ton, mape_ton = forecast_series(ton_series, horizon)
    fc_ves, _ = forecast_series(ves_series, horizon)
    sc_ton = apply_scenario(fc_ton, demand_pct, closure_start, closure_days)
    sc_ves = apply_scenario(fc_ves, demand_pct, closure_start, closure_days)

    # ---- KPI ----
    k1, k2, k3, k4, k5 = st.columns(5)
    tn, tp = cur.tonnes.sum(), prev.tonnes.sum()
    k1.metric(f"Son {window} gün yük", f"{fmt(tn / 1e6, 2)} Mt", f"{(tn / tp - 1) * 100:+.1f}%")
    vn, vp = cur_t.vessels.sum(), prev_t.vessels.sum()
    k2.metric("Gemi çağrısı", fmt(vn), f"{(vn / vp - 1) * 100:+.1f}%")
    wn, wp = cur_t.wait_h.mean(), prev_t.wait_h.mean()
    k3.metric("Ort. bekleme (saat)", fmt(wn, 1), f"{wn - wp:+.1f} sa", delta_color="inverse")
    k4.metric("Ort. rıhtım doluluğu", f"%{cur_t.berth_util.mean() * 100:.0f}")
    nxt = sc_ton.mid.iloc[:30].sum()
    last30 = ton_series.iloc[-30:].sum()
    k5.metric("Önümüzdeki 30 gün (tahmin)", f"{fmt(nxt / 1e6, 2)} Mt", f"{(nxt / last30 - 1) * 100:+.1f}%")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📊 Genel Bakış", "🗺️ Harita", "🔮 Tahmin", "🛢️ Tedarik Zinciri", "🧾 Veri"])

    # ======================= TAB 1: Genel Bakış =======================
    with tab1:
        c1, c2 = st.columns([3, 2])
        weekly = (cur.assign(week=cur.date.dt.to_period("W").dt.start_time)
                  .groupby(["week", "product"], as_index=False).tonnes.sum())
        fig = px.area(weekly, x="week", y="tonnes", color="product",
                      title="Haftalık yük hacmi (ton) — ürün bazında",
                      labels={"week": "", "tonnes": "Ton", "product": "Ürün"})
        fig.update_layout(legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=0))
        with c1:
            show(st.plotly_chart, fig)

        by_term = cur.groupby(["terminal", "direction"], as_index=False).tonnes.sum()
        fig = px.bar(by_term, x="tonnes", y="terminal", color="direction", orientation="h",
                     title="Terminal bazında yük (giriş / çıkış)",
                     labels={"tonnes": "Ton", "terminal": "", "direction": "Yön"},
                     color_discrete_map={"Giriş": "#2b7bba", "Çıkış": "#e8833a"})
        fig.update_layout(legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=0))
        with c2:
            show(st.plotly_chart, fig)

        c3, c4 = st.columns(2)
        heat = terms.assign(dow=terms.date.dt.dayofweek, month=terms.date.dt.month)
        heat = heat.groupby(["dow", "month"], as_index=False).vessels.mean()
        pivot = heat.pivot(index="dow", columns="month", values="vessels")
        pivot.index = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
        fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Blues",
                        labels=dict(x="Ay", y="", color="Gemi/gün"),
                        title="Ortalama günlük gemi çağrısı (gün × ay)")
        fig.update_layout(margin=dict(t=50, b=0))
        with c3:
            show(st.plotly_chart, fig)

        wt = cur_t.groupby("terminal", as_index=False).agg(wait=("wait_h", "mean"), util=("berth_util", "mean"))
        fig = px.scatter(wt, x="util", y="wait", size=[20] * len(wt), color="terminal", text="terminal",
                         title="Rıhtım doluluğu vs. bekleme süresi",
                         labels={"util": "Ort. rıhtım doluluğu", "wait": "Ort. bekleme (saat)"})
        fig.update_traces(textposition="top center")
        fig.update_layout(showlegend=False, margin=dict(t=50, b=0), xaxis_tickformat=".0%")
        with c4:
            show(st.plotly_chart, fig)

    # ======================= TAB 2: Harita =======================
    with tab2:
        st.subheader("Aliağa terminalleri")
        agg = cur.groupby("terminal", as_index=False).tonnes.sum()
        agg = agg.merge(cur_t.groupby("terminal", as_index=False).agg(
            wait=("wait_h", "mean"), vessels=("vessels", "sum")), on="terminal")
        agg["lat"] = agg.terminal.map(lambda t: TERMINALS[t]["lat"])
        agg["lon"] = agg.terminal.map(lambda t: TERMINALS[t]["lon"])
        agg["radius"] = 250 + 1100 * agg.tonnes / agg.tonnes.max()
        agg["tonnes_txt"] = (agg.tonnes / 1e3).round(0).map(lambda v: fmt(v))
        agg["wait_txt"] = agg.wait.round(1)

        layer = pdk.Layer("ScatterplotLayer", data=agg, get_position="[lon, lat]", get_radius="radius",
                          get_fill_color="[232, 131, 58, 170]", get_line_color="[120, 60, 10]",
                          line_width_min_pixels=1, stroked=True, pickable=True)
        text = pdk.Layer("TextLayer", data=agg, get_position="[lon, lat]", get_text="terminal",
                         get_size=13, get_color="[30, 30, 30]", get_pixel_offset="[0, -22]")
        tip = {"html": "<b>{terminal}</b><br/>Yük: {tonnes_txt} bin ton<br/>Gemi: {vessels}<br/>Ort. bekleme: {wait_txt} sa"}
        view = pdk.ViewState(latitude=ALIAGA_CENTER[0], longitude=ALIAGA_CENTER[1], zoom=11.3, pitch=0)
        show(st.pydeck_chart, pdk.Deck(layers=[layer, text], initial_view_state=view,
                                       tooltip=tip, map_style="light"))

        st.subheader("Bölgesel ve küresel akışlar")
        st.caption("Mavi: Aliağa'ya giriş (ithalat) · Turuncu: Aliağa'dan çıkış (ihracat). Kalınlık ≈ hacim.")
        prod_tn = cur.groupby("product").tonnes.sum()
        rows = []
        for name, lat, lon, prod, share in ROUTES:
            if prod not in prod_tn.index:
                continue
            tonnes = prod_tn[prod] * share
            inbound = PRODUCTS[prod]["dir"] == "Giriş"
            a, b = [lon, lat], [ALIAGA_CENTER[1], ALIAGA_CENTER[0]]
            rows.append(dict(route=f"{name.strip()} {'→' if inbound else '←'} Aliağa · {prod}",
                             src=a if inbound else b, dst=b if inbound else a,
                             tonnes=tonnes, tonnes_txt=fmt(tonnes / 1e3),
                             color=[43, 123, 186, 180] if inbound else [232, 131, 58, 180]))
        flows = pd.DataFrame(rows)
        if flows.empty:
            st.info("Seçili ürünler için rota verisi yok.")
        else:
            flows["width"] = 1 + 9 * flows.tonnes / flows.tonnes.max()
            arcs = pdk.Layer("ArcLayer", data=flows, get_source_position="src", get_target_position="dst",
                             get_source_color="color", get_target_color="color", get_width="width",
                             pickable=True, auto_highlight=True)
            view = pdk.ViewState(latitude=38, longitude=20, zoom=2.4, pitch=25)
            show(st.pydeck_chart, pdk.Deck(layers=[arcs], initial_view_state=view,
                                           tooltip={"html": "{route}<br/>{tonnes_txt} bin ton"},
                                           map_style="light"))

    # ======================= TAB 3: Tahmin =======================
    with tab3:
        targets = ["Toplam"] + [p for p in sel_prods if p in cargo["product"].unique()]
        target = st.selectbox("Tahmin edilecek seri", targets)
        if target == "Toplam":
            s_hist, fc, mape = ton_series, fc_ton, mape_ton
            sc = sc_ton
        else:
            s_hist = daily_series(cargo[cargo["product"] == target], "tonnes", all_dates)
            fc, mape = forecast_series(s_hist, horizon)
            sc = apply_scenario(fc, demand_pct, closure_start, closure_days)

        hist = s_hist.iloc[-120:]
        fig = go.Figure()
        fig.add_scatter(x=hist.index, y=hist.values, name="Gerçekleşen", line=dict(color="#555", width=1.5))
        fig.add_scatter(x=sc.index, y=sc.hi, line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=sc.index, y=sc.lo, fill="tonexty", fillcolor="rgba(232,131,58,0.2)",
                        line=dict(width=0), name="%95 aralık", hoverinfo="skip")
        fig.add_scatter(x=fc.index, y=fc.mid, name="Baz tahmin", line=dict(color="#2b7bba", dash="dot"))
        fig.add_scatter(x=sc.index, y=sc.mid, name="Senaryo", line=dict(color="#e8833a", width=2))
        fig.update_layout(title=f"Günlük yük tahmini — {target}", yaxis_title="Ton/gün",
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=0))
        show(st.plotly_chart, fig)

        m1, m2, m3 = st.columns(3)
        m1.metric("Backtest MAPE (son 28 gün)", f"%{mape:.1f}")
        m2.metric(f"{horizon} gün baz tahmin", f"{fmt(fc.mid.sum() / 1e6, 2)} Mt")
        m3.metric(f"{horizon} gün senaryo", f"{fmt(sc.mid.sum() / 1e6, 2)} Mt",
                  f"{(sc.mid.sum() / fc.mid.sum() - 1) * 100:+.1f}%")

        # Rıhtım doluluk tahmini
        util_hist = (ves_series * BERTH_DAYS_PER_VESSEL / berths_total).rolling(7).mean().iloc[-120:]
        util_fc = (sc_ves.mid * BERTH_DAYS_PER_VESSEL / berths_total)
        util_all = pd.concat([ves_series * BERTH_DAYS_PER_VESSEL / berths_total, util_fc]).rolling(7).mean()
        util_fc7 = util_all.loc[util_fc.index]
        fig = go.Figure()
        fig.add_scatter(x=util_hist.index, y=util_hist.values, name="Gerçekleşen (7g ort.)", line=dict(color="#555"))
        fig.add_scatter(x=util_fc7.index, y=util_fc7.values, name="Tahmin (senaryolu)", line=dict(color="#e8833a", width=2))
        fig.add_hline(y=0.85, line_dash="dash", line_color="crimson",
                      annotation_text="Tıkanıklık eşiği (%85)")
        fig.update_layout(title="Rıhtım doluluk tahmini (seçili terminaller)", yaxis_tickformat=".0%",
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=0))
        show(st.plotly_chart, fig)
        if (util_fc7 > 0.85).any():
            first = util_fc7[util_fc7 > 0.85].index[0].date()
            st.warning(f"⚠️ Tahmine göre rıhtım doluluğu {first} tarihinde %85 eşiğini aşıyor; bekleme süreleri artabilir.")

        weekly_fc = sc.mid.resample("W").sum().rename("Senaryo (ton)").to_frame()
        weekly_fc["Baz (ton)"] = fc.mid.resample("W").sum()
        weekly_fc.index = weekly_fc.index.date
        with st.expander("Haftalık tahmin tablosu"):
            show(st.dataframe, weekly_fc.round(0).astype(int))

    # ======================= TAB 4: Tedarik zinciri =======================
    with tab4:
        st.subheader("Rafineri ham petrol stok simülasyonu (Tüpraş İskeleleri)")
        st.caption("Tahmini ham petrol girişleri ile sabit işleme hızı arasındaki fark üzerinden tank stoğu simüle edilir. "
                   "Bu sekme terminal/ürün filtrelerinden bağımsızdır; senaryo kaydırıcıları geçerlidir.")
        crude = cargo_all[(cargo_all.terminal == "Tüpraş İskeleleri") & (cargo_all["product"] == "Ham Petrol")]
        crude_s = daily_series(crude, "tonnes", all_dates)
        fc_c, _ = forecast_series(crude_s, horizon)
        sc_c = apply_scenario(fc_c, demand_pct, closure_start, closure_days)

        default_proc = float(round(crude_s.iloc[-90:].mean() / 1e3, 1))
        a, b, c, d = st.columns(4)
        proc = a.slider("İşleme hızı (bin ton/gün)", 20.0, 50.0, default_proc, 0.5) * 1e3
        cap = b.slider("Tank kapasitesi (bin ton)", 300, 1500, 900, 50) * 1e3
        cover0 = c.slider("Başlangıç stok (gün)", 3, 25, 12)
        safety_days = d.slider("Emniyet stoğu (gün)", 1, 10, 5)

        start = min(cap, cover0 * proc)
        sims = {k: simulate_stock(sc_c[k].values, proc, cap, start) for k in ("lo", "mid", "hi")}
        idx = sc_c.index
        safety = safety_days * proc

        fig = go.Figure()
        fig.add_scatter(x=idx, y=sims["hi"] / 1e3, line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=idx, y=sims["lo"] / 1e3, fill="tonexty", fillcolor="rgba(43,123,186,0.2)",
                        line=dict(width=0), name="%95 aralık", hoverinfo="skip")
        fig.add_scatter(x=idx, y=sims["mid"] / 1e3, name="Beklenen stok", line=dict(color="#2b7bba", width=2))
        fig.add_hline(y=safety / 1e3, line_dash="dash", line_color="crimson", annotation_text="Emniyet stoğu")
        fig.add_hline(y=cap / 1e3, line_dash="dot", line_color="gray", annotation_text="Kapasite")
        fig.update_layout(title="Tahmini tank stoğu (bin ton)", yaxis_title="Bin ton",
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=0))
        show(st.plotly_chart, fig)

        s1, s2, s3 = st.columns(3)
        s1.metric("Ufuk sonu stok", f"{fmt(sims['mid'][-1] / 1e3)} bin ton",
                  f"{sims['mid'][-1] / proc:.1f} gün örtü")
        s2.metric("Minimum beklenen stok", f"{fmt(sims['mid'].min() / 1e3)} bin ton")
        s3.metric("Ort. günlük giriş / işleme", f"{fmt(sc_c.mid.mean() / 1e3, 1)} / {fmt(proc / 1e3, 1)} bin ton")

        below = idx[sims["mid"] < safety]
        below_lo = idx[sims["lo"] < safety]
        if len(below):
            st.error(f"🚨 Beklenen stok {below[0].date()} tarihinde emniyet seviyesinin altına düşüyor. "
                     "Ek ham petrol tedariki veya işleme hızı düşürme planlanmalı.")
        elif len(below_lo):
            st.warning(f"⚠️ Beklenen stok güvenli ancak kötü senaryoda (alt sınır) {below_lo[0].date()} tarihinde "
                       "emniyet stoğunun altına inebilir.")
        else:
            st.success("✅ Tahmin ufku boyunca stok emniyet seviyesinin üzerinde kalıyor.")

    # ======================= TAB 5: Veri =======================
    with tab5:
        st.caption("Sentetik veri — filtrelenmiş günlük kargo kayıtları")
        show(st.dataframe, cargo.sort_values("date", ascending=False).reset_index(drop=True), height=420)
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Kargo verisi (CSV)", cargo.to_csv(index=False).encode("utf-8-sig"),
                           "aliaga_kargo.csv", "text/csv")
        c2.download_button("⬇️ Terminal trafiği (CSV)", terms.to_csv(index=False).encode("utf-8-sig"),
                           "aliaga_terminal_trafigi.csv", "text/csv")


main()