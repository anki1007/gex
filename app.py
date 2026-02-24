import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. PAGE CONFIGURATION & CSS
# ==========================================
st.set_page_config(
    page_title="Live GEX Analyzer", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .live-indicator { display: inline-block; width: 10px; height: 10px; background-color: #22c55e; border-radius: 50%; margin-right: 5px; animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1f77b4; text-align: center; margin-bottom: 1rem; }
    </style>
    <div class="main-header">📊 Live GEX Analyzer</div>
""", unsafe_allow_html=True)

# ==========================================
# 2. BHARAT-SM-DATA INITIALIZATION
# ==========================================
@st.cache_resource
def init_apis():
    """Initialize the Sensibull and NSE API wrappers."""
    try:
        from Derivatives import Sensibull, NSE
        return Sensibull(), NSE()
    except ImportError:
        st.error("Missing dependencies. Ensure Bharat-sm-data and bs4 are in requirements.txt")
        st.stop()

sb, nse = init_apis()

@st.cache_data(ttl=300)
def get_symbol_info(symbol, is_index):
    """Fetch token and expiries, cached for 5 mins to prevent API spam."""
    try:
        token = sb.search_token(symbol)
        expiries = nse.get_options_expiry(symbol, is_index=is_index)
        return token, expiries
    except Exception as e:
        return None, []

# ==========================================
# 3. SIDEBAR CONFIGURATION
# ==========================================
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # 1. Select Asset Class
    asset_type = st.radio("Asset Type", ["Index", "Equity Stock"])
    is_index = True if asset_type == "Index" else False
    
    # 2. Select Symbol
    if is_index:
        symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
    else:
        symbol = st.text_input("Enter Stock Symbol (e.g., RELIANCE)", "RELIANCE").upper()
    
    # Fetch Data dynamically
    if symbol:
        token_info, available_expiries = get_symbol_info(symbol, is_index)
        
        if available_expiries:
            st.success("✅ Connected to Data Source")
            
            # 3. Dynamic Expiry Dropdown
            selected_expiry = st.selectbox("Select Expiry Date", available_expiries)
            
            # 4. Range Settings
            look_ups = st.slider(
                "Strikes to load (from ATM)", 
                min_value=5, max_value=30, value=15, step=5, 
                help="How many strikes above and below the ATM strike to fetch."
            )
            
            analyze_btn = st.button("🔄 Fetch & Analyze GEX", type="primary", use_container_width=True)
        else:
            st.error(f"❌ Could not locate data for {symbol}.")
            analyze_btn = False

# ==========================================
# 4. MAIN PROCESSING & VISUALIZATION
# ==========================================
if 'analyze_btn' in locals() and analyze_btn:
    with st.spinner(f"Fetching Live Data from Sensibull for {symbol}..."):
        try:
            # Fetch wide-format options data with Greeks
            greeks_df, atm_strike = sb.get_options_data_with_greeks(
                token_info, 
                num_look_ups_from_atm=look_ups, 
                expiry_date=selected_expiry
            )
            
            if greeks_df is not None and not greeks_df.empty:
                # Extract Spot Price safely
                spot_price = greeks_df['future_price'].iloc[0] if 'future_price' in greeks_df.columns else atm_strike
                
                # --- CALCULATE GEX USING SENSIBULL NATIVE GAMMA ---
                # Formula: OI * Gamma * Spot^2 * 0.01
                # Check if Greeks are actually returned by the API at this moment
                if 'CE.greeks_with_iv.gamma' in greeks_df.columns:
                    ce_gamma = greeks_df['CE.greeks_with_iv.gamma']
                    pe_gamma = greeks_df['PE.greeks_with_iv.gamma']
                else:
                    ce_gamma, pe_gamma = 0, 0
                    st.warning("⚠️ Live Greeks are currently unavailable from Sensibull (Market might be closed/resetting).")
                
                # Call GEX is positive, Put GEX is negative
                greeks_df['call_gex'] = greeks_df['CE.oi'] * ce_gamma * spot_price * spot_price * 0.01
                greeks_df['put_gex'] = greeks_df['PE.oi'] * pe_gamma * spot_price * spot_price * 0.01 * -1
                greeks_df['total_gex'] = greeks_df['call_gex'] + greeks_df['put_gex']
                
                net_gex = greeks_df['total_gex'].sum()
                regime = "Positive (Stabilizing) 🟢" if net_gex > 0 else "Negative (Volatile) 🔴"
                
                # --- RENDER TOP METRICS ---
                st.markdown(f'<span class="live-indicator"></span> <b>Live Chain ({selected_expiry.strftime("%d-%b-%Y")})</b>', unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("💰 Underlying Price", f"₹{spot_price:,.2f}")
                col2.metric("💹 Net GEX", f"{net_gex:,.0f}")
                col3.metric("📊 Market Regime", regime)
                
                st.markdown("---")
                
                # --- RENDER GEX CHART ---
                st.subheader(f"Gamma Exposure Profile - {symbol}")
                fig = go.Figure()
                fig.add_trace(go.Bar(x=greeks_df['strike'], y=greeks_df['call_gex'], name='Call GEX', marker_color='#2ca02c'))
                fig.add_trace(go.Bar(x=greeks_df['strike'], y=greeks_df['put_gex'], name='Put GEX', marker_color='#d62728'))
                fig.add_vline(x=spot_price, line_dash="dash", line_color="white", annotation_text="Spot Price")
                
                fig.update_layout(
                    barmode='relative', 
                    xaxis_title="Strike Price", 
                    yaxis_title="Gamma Exposure", 
                    template="plotly_dark", 
                    hovermode="x unified",
                    margin=dict(l=20, r=20, t=30, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # --- RENDER DATA TABLE ---
                st.subheader("Raw Options Data (Powered by Sensibull)")
                
                # Format the table neatly
                display_cols = [
                    'strike', 'CE.last_price', 'CE.oi', 'CE.greeks_with_iv.gamma', 
                    'PE.greeks_with_iv.gamma', 'PE.oi', 'PE.last_price', 'total_gex'
                ]
                # Only include columns that actually exist to prevent KeyErrors
                existing_cols = [col for col in display_cols if col in greeks_df.columns]
                
                formatted_df = greeks_df[existing_cols].copy()
                st.dataframe(formatted_df.round(4), use_container_width=True)
                
            else:
                st.warning("⚠️ Received empty data from Sensibull. The market might be closed or resetting.")
                
        except KeyError as ke:
            st.error(f"❌ Data structure error from Sensibull API (Missing Key: {str(ke)}). Try again later.")
        except Exception as e:
            st.error(f"❌ Failed to connect to Sensibull API: {str(e)}")
            st.info("💡 Tip: Sensibull servers often undergo maintenance between 11:30 PM and 6:00 AM IST.")

else:
    # Welcome Screen
    st.info("👈 Configure your symbol and expiry in the sidebar, then click 'Fetch & Analyze GEX'.")
    st.markdown("""
    ### Welcome to GEX Analyzer! 📈
    
    This tool analyzes **Gamma Exposure (GEX)** in Indian markets using institutional-grade data from Sensibull.
    
    **Features:**
    - 🔴 **Live Underlying Prices & OI**
    - 📊 Real-time Native Greeks (No Black-Scholes Approximations)
    - 📈 Interactive visualizations & GEX Profiling
    - 🏢 Supports both Indices (NIFTY) and Equities (RELIANCE)
    
    **What is Gamma Exposure (GEX)?**
    GEX represents the risk that market makers face. Large positive GEX (put-heavy) tends to suppress volatility as dealers hedge against the trend. Large negative GEX (call-heavy) tends to expand volatility as dealers hedge with the trend.
    """)
