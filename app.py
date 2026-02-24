import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Live GEX Analyzer (Sensibull)", 
    page_icon="📊", 
    layout="wide"
)

st.markdown("""
    <style>
    .live-indicator { display: inline-block; width: 10px; height: 10px; background-color: #22c55e; border-radius: 50%; margin-right: 5px; animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
    <h1 style='text-align: center; color: #1f77b4;'>📊 Live GEX Analyzer</h1>
""", unsafe_allow_html=True)

# ==========================================
# 2. BHARAT-SM-DATA INITIALIZATION
# ==========================================
@st.cache_resource
def init_bharat_sm():
    """Initialize the Sensibull and NSE API wrappers."""
    try:
        from Derivatives import Sensibull, NSE
        return Sensibull(), NSE()
    except ImportError:
        st.error("Missing dependency. Please run: pip install Bharat-sm-data bs4")
        st.stop()

sb, nse = init_bharat_sm()

# Cache token and expiry fetches to keep the UI snappy
@st.cache_data(ttl=300)
def get_symbol_info(symbol, is_index):
    try:
        token = sb.search_token(symbol)
        expiries = nse.get_options_expiry(symbol, is_index=is_index)
        return token, expiries
    except Exception as e:
        return None, []

# ==========================================
# 3. SIDEBAR CONFIGURATION & UI
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
        symbol = st.text_input("Enter Stock Symbol (e.g., RELIANCE, HDFCBANK)", "RELIANCE").upper()
    
    # Fetch Data dynamically based on selection
    if symbol:
        token_info, available_expiries = get_symbol_info(symbol, is_index)
        
        if available_expiries:
            st.success("✅ Connected to Data Source")
            
            # 3. Dynamic Expiry Dropdown
            selected_expiry = st.selectbox("Select Expiry Date", available_expiries)
            
            # 4. Strike Range Settings
            look_ups = st.slider("Strikes to load (from ATM)", 5, 30, 15, 5, 
                                 help="How many strikes above and below the ATM strike to fetch.")
            
            analyze_btn = st.button("🔄 Analyze GEX", type="primary", use_container_width=True)
        else:
            st.error(f"❌ Could not locate data for {symbol}.")
            analyze_btn = False

# ==========================================
# 4. MAIN PROCESSING & VISUALIZATION
# ==========================================
if 'analyze_btn' in locals() and analyze_btn:
    with st.spinner("Fetching Live Options Data & Greeks from Sensibull..."):
        try:
            # The library handles fetching OI, Prices, and Greeks in one call!
            greeks_df, atm_strike = sb.get_options_data_with_greeks(
                token_info, 
                num_look_ups_from_atm=look_ups, 
                expiry_date=selected_expiry
            )
            
            # Extract underlying future/spot price
            spot_price = greeks_df['future_price'].iloc[0]
            
            # Calculate Gamma Exposure (GEX) using the provided Greeks
            # Formula: OI * Gamma * Spot^2 * 0.01
            # Call GEX is positive, Put GEX is negative
            if 'CE.greeks_with_iv.gamma' in greeks_df.columns:
                ce_gamma = greeks_df['CE.greeks_with_iv.gamma']
                pe_gamma = greeks_df['PE.greeks_with_iv.gamma']
            else:
                ce_gamma, pe_gamma = 0, 0
                st.warning("Greeks are currently unavailable (Market might be closed or API is resetting).")
            
            greeks_df['call_gex'] = greeks_df['CE.oi'] * ce_gamma * spot_price * spot_price * 0.01
            greeks_df['put_gex'] = greeks_df['PE.oi'] * pe_gamma * spot_price * spot_price * 0.01 * -1
            greeks_df['total_gex'] = greeks_df['call_gex'] + greeks_df['put_gex']
            
            net_gex = greeks_df['total_gex'].sum()
            regime = "Positive (Stabilizing) 🟢" if net_gex > 0 else "Negative (Volatile) 🔴"
            
            # Render Top Metrics
            st.markdown(f'<span class="live-indicator"></span> <b>Live Chain ({selected_expiry.strftime("%d-%b-%Y")})</b>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            col1.metric("💰 Underlying Price", f"₹{spot_price:,.2f}")
            col2.metric("💹 Net GEX", f"{net_gex:,.0f}")
            col3.metric("📊 Market Regime", regime)
            
            st.markdown("---")
            
            # Render Chart
            st.subheader("Gamma Exposure Profile")
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
            
            # Render Data Table
            st.subheader("Raw Options Data (Powered by Sensibull)")
            display_cols = ['strike', 'CE.last_price', 'CE.oi', 'CE.greeks_with_iv.gamma', 
                            'PE.greeks_with_iv.gamma', 'PE.oi', 'PE.last_price', 'total_gex']
            
            # Filter columns that actually exist to prevent KeyError
            existing_cols = [col for col in display_cols if col in greeks_df.columns]
            st.dataframe(greeks_df[existing_cols].round(4), use_container_width=True)
            
        except Exception as e:
            st.error(f"Error processing options data: {str(e)}")
            st.info("Check if the market is open or if the symbol is valid.")

else:
    st.info("👈 Configure your symbol and expiry in the sidebar, then click 'Analyze GEX'.")
