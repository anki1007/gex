import streamlit as st
import pandas as pd
import requests
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from scipy.stats import norm
import time

# ==========================================
# 1. PAGE CONFIG & CSS
# ==========================================
st.set_page_config(page_title="Live GEX Analyzer", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    .metric-card { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
    .live-indicator { display: inline-block; width: 10px; height: 10px; background-color: #22c55e; border-radius: 50%; margin-right: 5px; animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. NSE DATA FETCHER (With Anti-Ban Logic)
# ==========================================
@st.cache_data(ttl=120) # Cache for 2 minutes to prevent NSE IP Block
def fetch_nse_live_data(symbol="NIFTY"):
    url_oc = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    url_base = "https://www.nseindia.com"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    session = requests.Session()
    try:
        # Step 1: Hit homepage to get valid session cookies
        session.get(url_base, headers=headers, timeout=10)
        time.sleep(1) # Brief pause to mimic human
        
        # Step 2: Hit API endpoint
        response = session.get(url_oc, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None, None, f"NSE API Error: {response.status_code}"
            
        data = response.json()
        
        # Parse Expiry Dates
        expiries = data['records']['expiryDates']
        current_expiry = expiries[0] # Next nearest expiry
        
        # Extract Spot Price
        spot_price = data['records']['underlyingValue']
        
        # Parse Option Chain
        records = data['records']['data']
        df_list = []
        
        for item in records:
            if item['expiryDate'] == current_expiry:
                strike = item['strikePrice']
                
                # CE Data
                if 'CE' in item:
                    ce = item['CE']
                    df_list.append({
                        'strike': strike, 'type': 'CE', 'oi': ce['openInterest'] * 50, # Rough lot size conversion
                        'iv': ce['impliedVolatility'], 'ltp': ce['lastPrice']
                    })
                # PE Data
                if 'PE' in item:
                    pe = item['PE']
                    df_list.append({
                        'strike': strike, 'type': 'PE', 'oi': pe['openInterest'] * 50,
                        'iv': pe['impliedVolatility'], 'ltp': pe['lastPrice']
                    })
                    
        df = pd.DataFrame(df_list)
        
        # Filter zero IVs which break Black-Scholes
        df['iv'] = df['iv'].replace(0, 0.001) 
        
        return df, spot_price, current_expiry
        
    except Exception as e:
        return None, None, str(e)

# ==========================================
# 3. OPTIONS MATH (Black-Scholes & GEX)
# ==========================================
def calculate_gamma(S, K, T, r, sigma):
    """Calculate Black-Scholes Gamma"""
    # Protect against divide by zero
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return gamma

def process_gex(df, spot_price, r=0.07, days_to_expiry=1):
    """Calculate Gamma Exposure"""
    T = days_to_expiry / 365.0
    
    # Pivot dataframe so CE and PE are on the same row per strike
    df_pivot = df.pivot(index='strike', columns='type', values=['oi', 'iv']).fillna(0)
    df_pivot.columns = ['_'.join(col).strip() for col in df_pivot.columns.values]
    df_pivot = df_pivot.reset_index()
    
    # Calculate Gamma for each strike
    # Using Call IV for simplicity, though realistically CE and PE IV differ slightly
    df_pivot['gamma'] = df_pivot.apply(
        lambda x: calculate_gamma(spot_price, x['strike'], T, r, x['iv_CE']/100), axis=1
    )
    
    # Calculate GEX (Assuming 1 Contract = 1 unit of underlying for simplification in index)
    # Market Maker perspective: Short Calls (Negative Gamma), Short Puts (Positive Gamma) 
    # Standard Retail view: Call OI * Gamma = Positive, Put OI * Gamma = Negative
    df_pivot['call_gex'] = df_pivot['oi_CE'] * df_pivot['gamma'] * spot_price * spot_price * 0.01
    df_pivot['put_gex'] = df_pivot['oi_PE'] * df_pivot['gamma'] * spot_price * spot_price * 0.01 * -1
    
    df_pivot['total_gex'] = df_pivot['call_gex'] + df_pivot['put_gex']
    
    return df_pivot

# ==========================================
# 4. STREAMLIT UI
# ==========================================
st.markdown('<h1 style="text-align: center; color: #1f77b4;">📊 Live GEX Analyzer</h1>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Configuration")
    symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY"])
    strike_range = st.slider("Range around spot (%)", 2, 10, 5, 1)
    
    if st.button("🔄 Fetch Live NSE Data", type="primary", use_container_width=True):
        st.session_state.fetch_trigger = True

# Initialize state
if 'fetch_trigger' not in st.session_state:
    st.session_state.fetch_trigger = False

if st.session_state.fetch_trigger:
    with st.spinner("Bypassing NSE security and fetching live data..."):
        df, spot, expiry = fetch_nse_live_data(symbol)
        
        if df is None:
            st.error(f"❌ Failed to fetch data. Error: {expiry}")
            st.info("Try waiting 2 minutes and clicking fetch again, or check your internet connection.")
        else:
            # Filter strikes
            lower_bound = spot * (1 - (strike_range/100))
            upper_bound = spot * (1 + (strike_range/100))
            
            df_filtered = df[(df['strike'] >= lower_bound) & (df['strike'] <= upper_bound)]
            
            # Calculate GEX
            gex_df = process_gex(df_filtered, spot)
            
            # Metrics
            net_gex = gex_df['total_gex'].sum()
            regime = "Positive (Stabilizing)" if net_gex > 0 else "Negative (Volatile)"
            
            # Top UI
            st.markdown(f'<span class="live-indicator"></span> <b>Live Options Chain ({expiry})</b>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            col1.metric("💰 Spot Price", f"₹{spot:,.2f}")
            col2.metric("💹 Net GEX", f"{net_gex:,.0f}")
            col3.metric("📊 Market Regime", regime)
            
            # Visualizations
            st.markdown("---")
            st.subheader("Gamma Exposure Profile")
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=gex_df['strike'], y=gex_df['call_gex'],
                name='Call GEX', marker_color='green', opacity=0.7
            ))
            fig.add_trace(go.Bar(
                x=gex_df['strike'], y=gex_df['put_gex'],
                name='Put GEX', marker_color='red', opacity=0.7
            ))
            fig.add_vline(x=spot, line_dash="dash", line_color="white", annotation_text="Spot Price")
            
            fig.update_layout(
                barmode='relative',
                xaxis_title="Strike Price",
                yaxis_title="Gamma Exposure",
                template="plotly_dark",
                hovermode="x unified"
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Data Table
            st.subheader("Raw GEX Data")
            st.dataframe(gex_df.round(2), use_container_width=True)
else:
    st.info("👈 Click 'Fetch Live NSE Data' in the sidebar to begin.")
