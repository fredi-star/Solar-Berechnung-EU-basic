import streamlit as st
import requests
import pandas as pd
import numpy as np
from geopy.geocoders import Nominatim

# ---------------------------------------------------------
# 1. HELPER FUNCTIONS
# ---------------------------------------------------------
def calculate_irr(cashflows, guess=0.1):
    rate = guess
    for _ in range(100):
        try:
            npv = sum([cf / ((1 + rate) ** i) for i, cf in enumerate(cashflows)])
            derivative = sum([-i * cf / ((1 + rate) ** (i + 1)) for i, cf in enumerate(cashflows)])
            if abs(derivative) < 1e-10:
                return None
            new_rate = rate - npv / derivative
            if abs(new_rate - rate) < 1e-7:
                return new_rate
            rate = new_rate
        except:
            return None
    return None

def get_coordinates(address):
    geolocator = Nominatim(user_agent="solar_asset_manager_pro_v5")
    try:
        location = geolocator.geocode(address)
        if location:
            return location.latitude, location.longitude
        return None, None
    except:
        return None, None

@st.cache_data
def get_pvgis_data(lat, lon, kwp, angle, aspect, loss=14):
    if kwp <= 0:
        return 0
    url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
    # Here we take your inputs for tilt/orientation
    params = {
        'lat': lat, 'lon': lon, 'peakpower': kwp,
        'loss': loss, 'outputformat': 'json',
        'angle': angle, 'aspect': aspect
    }
    try:
        r = requests.get(url, params=params)
        return r.json()['outputs']['totals']['fixed']['E_y']
    except:
        return None

def parse_de_number(value):
    """
    Parse numbers that might use a German decimal comma.
    Accepts str, int, float. If str, replaces comma with dot and converts to float.
    Returns float or None if conversion fails.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except:
            return None
    return None


def format_de(number, decimals=2, currency=None):
    """
    Format a number using German locale style: '.' as thousand separator and ',' as decimal separator.
    Example: 12345.67 -> '12.345,67'
    """
    try:
        if number is None:
            return "n/a" if not currency else f"n/a {currency}"
        # Ensure number is float
        num = float(number)
        s = f"{num:,.{decimals}f}"  # e.g., '12,345.67'
        # swap separators: ',' -> temporary, '.' -> ',', temporary -> '.'
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        if currency:
            s = f"{s} {currency}"
        return s
    except:
        return str(number)

# ---------------------------------------------------------
# 2. UI & INPUTS
# ---------------------------------------------------------
st.set_page_config(page_title="Commercial Solar Manager", layout="wide")
st.title("Commercial Solar Asset Manager")
st.markdown("Professional **Yield-Co Analysis** (IRR, NPV, Payback).")
st.caption("Note: Output numbers use the German decimal separator (comma).")

col1, col2, col3 = st.columns(3)

with col1:
    st.header("1. Asset Data")
    addr = st.text_input("Location", "Mönckebergstraße, Hamburg")
    lat, lon = 53.55, 9.99
    if addr:
        f_lat, f_lon = get_coordinates(addr)
        if f_lat:
            lat, lon = f_lat, f_lon

    st.write(f"{lat:.4f}, {lon:.4f}")

    # --- TECHNICAL UPGRADE ---
    c_tech1, c_tech2 = st.columns(2)
    with c_tech1:
        angle = st.slider("Tilt (°)", 0, 90, 35)  # 0=Flat
    with c_tech2:
        aspect = st.slider("Orientation (°)", -180, 180, 0)  # 0=South

    area = st.number_input("Area (m²)", value=500.0)
    kwp = area / 6.0
    st.info(f"Capacity: **{format_de(kwp, 2)} kWp**")

with col2:
    st.header("2. Investment")
    invest_type = st.radio("CAPEX Method", ["€/kWp", "Total"])
    if invest_type == "€/kWp":
        price_kwp = st.number_input("Price/kWp (€)", value=1100.0)
        capex = kwp * price_kwp
    else:
        capex = st.number_input("Total Investment (€)", value=100000.0)

    st.metric("Total CAPEX", format_de(capex, 2, '€'))
    opex_pct = st.number_input("OPEX (Operating costs in % of investment)", value=1.0) / 100
    opex_fix = capex * opex_pct

with col3:
    st.header("3. Revenue Model")
    self_use = st.slider("Self-consumption in %", 0, 100, 40) / 100
    p_industry = st.number_input("Electricity Purchase Price (Save) ct/kWh", value=28.0) / 100
    p_market = st.number_input("Electricity Selling Price (Sell) ct/kWh", value=8.0) / 100
    wacc = st.number_input("Cost of Capital %", value=6.0) / 100

st.markdown("---")
with st.expander("Fine-Tuning Settings"):
    c1, c2, c3 = st.columns(3)
    with c1:
        degr_avg = st.number_input("Degradation Expected (%)", value=0.5) / 100
        degr_worst = st.number_input("Degradation Worst Case (%)", value=1.0) / 100
    with c2:
        infl_avg = st.number_input("Inflation (%)", value=2.0) / 100
        merit_drop = st.number_input("Merit-Order Price Drop (%)", value=1.0) / 100
    with c3:
        inv_cost = st.number_input("Major Replacement Cost (€)", value=2000.0)
        inv_year = st.slider("Replacement Year", 1, 20, 10)

# ---------------------------------------------------------
# 3. CALCULATION
# ---------------------------------------------------------
if st.button("Calculate Case"):
    # API call now with angle & aspect
    start_yield = get_pvgis_data(lat, lon, kwp, angle, aspect) if kwp > 0 else 0

    if start_yield is not None:
        years = range(1, 21)

        res_avg, res_worst = [], []
        flows_avg = [-capex]
        flows_worst = [-capex]

        cum_avg, cum_worst = -capex, -capex

        for y in years:
            # A. AVERAGE EXPECTED CASE
            prod_a = start_yield * ((1 - degr_avg) ** (y - 1))
            p_ind_a = p_industry * ((1 + infl_avg) ** (y - 1))
            p_mark_a = p_market * ((1 + infl_avg) ** (y - 1))

            rev_a = (prod_a * self_use * p_ind_a) + (prod_a * (1 - self_use) * p_mark_a)
            cost_a = opex_fix * ((1 + infl_avg) ** (y - 1))

            cf_a = rev_a - cost_a
            flows_avg.append(cf_a)
            cum_avg += cf_a
            res_avg.append(cum_avg)

            # B. WORST CASE
            prod_w = start_yield * ((1 - degr_worst) ** (y - 1))
            p_mark_w = p_market * ((1 - merit_drop) ** (y - 1))

            rev_w = (prod_w * self_use * p_industry) + (prod_w * (1 - self_use) * p_mark_w)
            cost_w = opex_fix * ((1 + infl_avg) ** (y - 1))

            invest_fix = inv_cost if y == inv_year else 0

            cf_w = rev_w - cost_w - invest_fix
            flows_worst.append(cf_w)
            cum_worst += cf_w
            res_worst.append(cum_worst)

        # OUTPUTS
        st.markdown("### Performance")

        try:
            npv_avg = sum([cf / ((1 + wacc) ** i) for i, cf in enumerate(flows_avg)])
            npv_worst = sum([cf / ((1 + wacc) ** i) for i, cf in enumerate(flows_worst)])
        except:
            npv_avg, npv_worst = 0, 0

        irr_avg = calculate_irr(flows_avg)
        irr_display = f"{format_de(irr_avg * 100, 2)}%" if irr_avg else "n/a"

        payback_avg = next((i for i, x in enumerate(res_avg) if x >= 0), ">20")
        payback_worst = next((i for i, x in enumerate(res_worst) if x >= 0), ">20")

        st.subheader("Average Expected Case")
        k1, k2, k3 = st.columns(3)

        # Logic for color and text
        delta_val = "Profitable" if npv_avg > 0 else "Loss-making"
        delta_col = "normal" if npv_avg > 0 else "inverse"  # Streamlit logic: normal=green, inverse=red (for delta)

        k1.metric("NPV", format_de(npv_avg, 0, '€'), delta=delta_val, delta_color=delta_col)
        k2.metric("IRR", irr_display)
        k3.metric("Payback Period", f"{payback_avg} Years")

        st.subheader("Assumed Worst-Case Development")
        w1, w2, w3 = st.columns(3)
        w1.metric("NPV", format_de(npv_worst, 0, '€'), delta_color="off")
        w2.metric("IRR", "Not calculable", help="Sign change unstable.")
        w3.metric("Payback Period", f"{payback_worst} Years")

        st.markdown("---")
        st.subheader("Cash Flows")
        chart_data = pd.DataFrame({
            "Year": years,
            "Average Expected Case": res_avg,
            "Assumed Worst-Case Development": res_worst
        })
        st.line_chart(chart_data, x="Year", y=["Average Expected Case", "Assumed Worst-Case Development"])

        if npv_avg > 0 and npv_worst < 0:
            st.warning("**Risk Notice:** Project is profitable in the expected case, but loses money in the worst case.")
        elif npv_worst > 0:
            st.success("**Strong Buy:** Project is profitable even in the worst case (including expensive replacement parts).")
