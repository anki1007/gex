import streamlit as st
import pandas as pd
from datetime import datetime

# Import custom modules
from modules.data_fetcher import (
    fetch_option_chain, 
    get_available_expiries,
    get_index_quote,
    get_market_status
)
from modules.gex_calculator import calculate_gex, find_gamma_levels
from modules.visualizations import (
    plot_gex_profile, 
    plot_spot_gex_levels, 
    plot_oi_analysis,
    plot_pcr_analysis
)
from modules.utils import get_atm_strike, format_number, filter_strikes

# Page configuration
st.set_page_config(
    page_title="GEX Analyzer - Live Data",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .live-indicator {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #22c55e;
        border-radius: 50%;
        margin-right: 5px;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'options_df' not in st.session_state:
    st.session_state.options_df = None
if 'spot_price' not in st.session_state:
    st.session_state.spot_price = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# Header
st.markdown('<p class="main-header">📊 GEX Analyzer</p>', unsafe_allow_html=True)
st.markdown("### Gamma Exposure Analysis for NSE Options")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    asset_type = st.radio("Asset Type", ["Index", "Equity Stock"])
    is_index = True if asset_type == "Index" else False
    
    if is_index:
        symbol = st.selectbox("Select Index", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
    else:
        symbol = st.text_input("Enter Stock Symbol (e.g., RELIANCE)", "RELIANCE").upper()
    
    if symbol:
        available_expiries = get_available_expiries(symbol, is_index)
        
        if available_expiries:
            st.success("✅ Connected to Data Source")
            expiry_date = st.selectbox("Select Expiry Date", available_expiries)
            
            st.subheader("📍 Strike Range")
            strike_range = st.slider("Range around spot (%)", min_value=5, max_value=20, value=10, step=1)
            
            if st.button("🔄 Fetch Data", type="primary", use_container_width=True):
                with st.spinner("Fetching data from Sensibull..."):
                    df, spot = fetch_option_chain(symbol, expiry_date, is_index)
                    
                    if df is not None and not df.empty and spot is not None:
                        st.session_state.options_df = df
                        st.session_state.spot_price = spot
                        st.session_state.data_loaded = True
                        st.session_state.last_update = datetime.now()
                        st.success(f"✅ Live data loaded! Spot: ₹{spot:,.2f}")
                    else:
                        st.error("❌ Failed to fetch option chain. Market may be closed.")
        else:
            st.warning("⚠️ Could not load expiries.")

    st.subheader("🔧 Parameters")
    risk_free_rate = st.number_input("Risk-Free Rate (%)", min_value=0.0, max_value=15.0, value=7.0, step=0.1) / 100
    
    if st.session_state.data_loaded and st.session_state.last_update:
        st.markdown("---")
        st.markdown('<span class="live-indicator"></span> Live Data', unsafe_allow_html=True)
        st.caption(f"🕐 Updated: {st.session_state.last_update.strftime('%H:%M:%S')}")
        st.caption(f"📊 {symbol} Spot: ₹{st.session_state.spot_price:,.2f}")

# Main content
if st.session_state.data_loaded:
    df = st.session_state.options_df
    spot_price = st.session_state.spot_price
    
    df_filtered = filter_strikes(df, spot_price, strike_range)
    
    with st.spinner("Calculating GEX..."):
        gex_df = calculate_gex(df_filtered, spot_price, expiry_date, risk_free_rate)
        gamma_levels = find_gamma_levels(gex_df, spot_price)
    
    st.markdown("---")
    st.subheader("📈 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("💰 Spot Price", f"₹{spot_price:,.2f}", delta=None)
    
    with col2:
        flip_diff = gamma_levels['gamma_flip'] - spot_price
        st.metric("🔄 Gamma Flip", f"₹{gamma_levels['gamma_flip']:,.0f}", delta=f"{flip_diff:+.0f}", delta_color="off")
    
    with col3:
        regime = "Positive Gamma" if gamma_levels['total_gex'] > 0 else "Negative Gamma"
        regime_color = "🟢" if gamma_levels['total_gex'] > 0 else "🔴"
        st.metric("📊 Market Regime", f"{regime_color} {regime}", delta=None)
    
    with col4:
        st.metric("💹 Net GEX", format_number(gamma_levels['total_gex']), delta=None)
    
    # --- FULLY RESTORED TABS (Including Tab 4) ---
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 GEX Profile",
        "📉 OI Analysis",
        "📋 Data Table",
        "ℹ️ Information"
    ])
    
    with tab1:
        st.subheader("Gamma Exposure Profile")
        fig_gex = plot_gex_profile(gex_df, spot_price, gamma_levels)
        st.plotly_chart(fig_gex, use_container_width=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("##### 🎯 Key Levels")
            st.write(f"**Support Level:** ₹{gamma_levels.get('support', 'N/A'):,}")
            st.write(f"**Resistance Level:** ₹{gamma_levels.get('resistance', 'N/A'):,}")
            st.write(f"**ATM Strike:** ₹{get_atm_strike(spot_price):,}")
        with col2:
            st.markdown("##### 📊 GEX Summary")
            st.write(f"**Total Call GEX:** {format_number(gex_df['call_gex'].sum())}")
            st.write(f"**Total Put GEX:** {format_number(gex_df['put_gex'].sum())}")
            st.write(f"**Net GEX:** {format_number(gex_df['total_gex'].sum())}")
        
        st.markdown("---")
        st.subheader("Net GEX vs Spot Movement")
        fig_spot_gex = plot_spot_gex_levels(gex_df, spot_price, gamma_levels, price_range=500)
        st.plotly_chart(fig_spot_gex, use_container_width=True)
    
    with tab2:
        st.subheader("Open Interest Analysis")
        fig_oi = plot_oi_analysis(df_filtered, spot_price)
        st.plotly_chart(fig_oi, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Put-Call Ratio (PCR) Analysis")
        fig_pcr = plot_pcr_analysis(df_filtered)
        st.plotly_chart(fig_pcr, use_container_width=True)
        
        total_call_oi = df_filtered[df_filtered['type'] == 'CE']['oi'].sum()
        total_put_oi = df_filtered[df_filtered['type'] == 'PE']['oi'].sum()
        overall_pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Call OI", f"{total_call_oi:,.0f}")
        col2.metric("Total Put OI", f"{total_put_oi:,.0f}")
        col3.metric("Overall PCR", f"{overall_pcr:.2f}")
    
    with tab3:
        st.subheader("GEX Data Table")
        display_df = gex_df.copy()
        display_df['call_gex'] = display_df['call_gex'].apply(lambda x: f"{x:,.0f}")
        display_df['put_gex'] = display_df['put_gex'].apply(lambda x: f"{x:,.0f}")
        display_df['total_gex'] = display_df['total_gex'].apply(lambda x: f"{x:,.0f}")
        
        st.dataframe(display_df, use_container_width=True, height=400)
        
        csv = gex_df.to_csv(index=False)
        st.download_button(
            label="📥 Download GEX Data (CSV)",
            data=csv,
            file_name=f"gex_data_{symbol}_{expiry_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    
    with tab4:
        st.subheader("ℹ️ Understanding GEX")
        st.markdown("""
        **What is Gamma Exposure (GEX)?**
        Gamma Exposure represents the risk that market makers face due to their options positions. 
        It indicates how much dealers need to hedge their positions as the underlying price moves.
        
        **Key Concepts:**
        - **Positive GEX (Put-heavy)**: Market makers are long gamma. They sell when price rises and buy when it falls, creating a stabilizing effect. Markets tend to be less volatile.
        - **Negative GEX (Call-heavy)**: Market makers are short gamma. They buy when price rises and sell when it falls, creating a destabilizing effect. Markets tend to be more volatile.
        - **Gamma Flip Point**: The price level where GEX changes from positive to negative (or vice versa). This level often acts as a pivot point for market behavior.
        
        **How to Use This Tool:**
        1. **Check Market Regime**: Positive or Negative Gamma environment
        2. **Identify Key Levels**: Support, Resistance, and Gamma Flip points
        3. **Analyze GEX Distribution**: Where is gamma concentrated?
        4. **Monitor Changes**: Track how GEX evolves throughout the day
        
        **Data Source:** Powered by Sensibull (Bharat-sm-data)
        """)
        st.info("💡 **Tip**: Combine GEX analysis with price action, volume, and other indicators for best results.")
        st.warning("⚠️ **Disclaimer**: For educational purposes only. Not financial advice.")

else:
    # --- FULLY RESTORED WELCOME SCREEN ---
    st.info("👈 Configure settings in the sidebar and click 'Fetch Data' to begin analysis")
    
    st.markdown("""
    ### Welcome to GEX Analyzer! 📊
    
    This tool analyzes **Gamma Exposure (GEX)** in NSE options with **LIVE data** using Sensibull via Bharat-sm-data.
    
    **Features:**
    - 🔴 **Live Spot Prices** & Options Chain
    - 📊 Real-time GEX calculations
    - 📈 Interactive visualizations
    - 🎯 Key support/resistance levels
    - 💹 Put-Call Ratio analysis
    - 📥 Downloadable data
    - 🔄 Market regime identification
    """)
    
    st.markdown("---")
    st.subheader("📈 Current Market Levels")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    padding: 1.5rem; border-radius: 10px; color: white;'>
            <h4 style='margin: 0; color: white;'>NIFTY 50</h4>
            <p style='margin: 0; font-size: 0.9em;'>Awaiting API Connection...</p>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); 
                    padding: 1.5rem; border-radius: 10px; color: white;'>
            <h4 style='margin: 0; color: white;'>BANK NIFTY</h4>
            <p style='margin: 0; font-size: 0.9em;'>Awaiting API Connection...</p>
        </div>
        """, unsafe_allow_html=True)
    
    market_status = get_market_status()
    st.caption(f"🟢 Market Status: {market_status['market_state']} | Updated: {market_status['timestamp']}")
    st.markdown("---")
    st.info("💡 **Tip**: Click 'Fetch Data' to pull the live options chain and populate the GEX charts!")
