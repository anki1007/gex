"""
Data fetching module using Bharat-sm-data (Sensibull)
"""
import pandas as pd
from datetime import datetime
import streamlit as st

@st.cache_resource
def get_apis():
    from Derivatives import Sensibull, NSE
    return Sensibull(), NSE()

def fetch_option_chain(symbol, expiry_date_str, is_index=True, look_ups=20):
    """
    Fetch option chain data and native Greeks using Sensibull.
    Returns: (DataFrame with options data, spot price)
    """
    try:
        sb, nse = get_apis()
        token = sb.search_token(symbol)
        
        # Fetch wide-format options data with live Greeks
        sb_df, atm = sb.get_options_data_with_greeks(
            token, 
            num_look_ups_from_atm=look_ups, 
            expiry_date=expiry_date_str
        )
        
        if sb_df is None or sb_df.empty:
            return None, None
            
        spot_price = sb_df['future_price'].iloc[0] if 'future_price' in sb_df.columns else atm
        
        # Translate wide format to the long format your modules expect
        options_data = []
        for _, row in sb_df.iterrows():
            strike = row.get('strike', 0)
            
            # Calls
            options_data.append({
                'strike': strike,
                'type': 'CE',
                'oi': row.get('CE.oi', 0),
                'iv': row.get('CE.implied_volatility', 0),
                'ltp': row.get('CE.last_price', 0),
                'native_gamma': row.get('CE.greeks_with_iv.gamma', None)
            })
            
            # Puts
            options_data.append({
                'strike': strike,
                'type': 'PE',
                'oi': row.get('PE.oi', 0),
                'iv': row.get('PE.implied_volatility', 0),
                'ltp': row.get('PE.last_price', 0),
                'native_gamma': row.get('PE.greeks_with_iv.gamma', None)
            })
            
        df = pd.DataFrame(options_data)
        return df, spot_price
        
    except Exception as e:
        print(f"Error fetching option chain from Sensibull: {e}")
        return None, None

@st.cache_data(ttl=300)
def get_available_expiries(symbol, is_index=True):
    """Fetch expiries directly from NSE"""
    try:
        _, nse = get_apis()
        return nse.get_options_expiry(symbol, is_index=is_index)
    except:
        return []
