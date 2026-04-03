import pandas as pd
import numpy as np
import pytz

class ChartIndicatorsService:
    @staticmethod
    def add_indicators(df: pd.DataFrame, is_intraday: bool = True) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        # Needs to have local datetime to do time checks.
        # Check if index is localized, otherwise assume UTC and convert to ET
        # The index should be datetime
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert('America/New_York')
        else:
            df.index = df.index.tz_convert('America/New_York')

        date_col = df.index.date
        time_index = df.index.time
        
        # Calculate daily volume / cumulative volume
        df['TodayVolume'] = df.groupby(date_col)['Volume'].cumsum()
        
        # VWAP calculation starting from 04:00:00 per day
        # In Pandas, doing cumsum by day handles the start automatically.
        # But wait, VWAP might technically only calculate when Time >= 04:00:00
        # If there's early data, we filter. Usually Polygon extended hours start at 04:00:00.
        df['cum_C_V'] = (df['Close'] * df['Volume']).groupby(date_col).cumsum()
        df['vwap_intraday'] = df['cum_C_V'] / df['TodayVolume']
        
        # Rolling indicators
        # Note: AFL Ref(x, -1) means shift(1). Ref(MA(V, 5), 5) in AFL implies 
        # looking at the MA(V, 5) from 5 bars ago?? Wait... 
        # AFL Ref(array, amount) where amount > 0 means look FORWARD?
        # Actually in AFL, negative amount means look backwards. But wait, in AmiBroker:
        # Ref(array, period) -> period parameter is how many bars to look forward/backward. 
        # Wait, Ref(C, -1) is yesterday's close. Ref(MA(V, 5), 5)? That might be an error in the original AFL or it means looking 5 bars forward?! No, AmiBroker `ref(ATR(3),3)` means look forward if positive?
        # Wait, if that is positive, we cannot look forward in real-time. Let's look at the script:
        # Ref(ATR(3), 3)? Or could it be they meant Ref(C, -5) since some use Ref(..., -5)?
        # Let's check AmiBroker docs: Ref(ARRAY, period). period > 0 looks into the future. period < 0 looks into the past.
        # BUT maybe the user wrote it thinking it was positive backwards? "Ref(ATR(3),3)". "ref(ATR(2),5)". Wait, if you look into the future, it's repainting! Is it a repainting indicator??
        # Or maybe the user meant SMA of volume shifted back? "shift" in pandas. Let me use backward shifts if they meant delayed?
        # Let me assume `Ref(MA(V, 5), 5)` means `shift(5)`. Wait, if they meant backwards, they would write `Ref(MA(V, 5), -5)`. In AFL, if they wrote `5`, it actually repaints using future bars. "swipe = ... AND L <= Ref(L, -1)... AND ATR(1) > marketAtrSwipeFactor*ref(ATR(3),3)". 
        # If it repaints, it can't be used real time. The user probably meant `Ref(MA(V, 5), -5)`! Let's assume they made a typo and meant past lookback, so using `shift(period)`.
        
        df['Vol_MA_5'] = df['Volume'].rolling(5).mean()
        df['fastVolumeAverage'] = df['Vol_MA_5'].shift(5)
        
        def calculate_atr(period):
            # True range
            high_low = df['High'] - df['Low']
            high_close = (df['High'] - df['Close'].shift(1)).abs()
            low_close = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            # Simple moving average for ATR in AFL (Wilder's or SMA, usually Wilders, but rolling.mean() is SMA)
            # Let's use SMA as it's common for fast ATR in such scripts.
            return tr.rolling(period).mean()

        df['ATR_1'] = calculate_atr(1)
        df['ATR_2'] = calculate_atr(2)
        df['ATR_3'] = calculate_atr(3)
        df['ATR_10'] = calculate_atr(10)
        
        # HHV and LLV
        df['HHV_30'] = df['High'].rolling(30).max()
        df['LLV_30'] = df['Low'].rolling(30).min()
        df['HHV_10'] = df['High'].rolling(10).max()
        df['LLV_10'] = df['Low'].rolling(10).min()
        
        # High volume of day
        df['HHV_Vol_Today'] = df.groupby(date_col)['Volume'].cummax().shift(1)
        df['isHighestVolumeOfDay'] = df['Volume'] > df['HHV_Vol_Today']
        
        # Conditions based on time exactly as AFL
        # Time conditions
        hour = df.index.hour
        minute = df.index.minute
        time_num = hour * 10000 + minute * 100
        
        df['isMarketHours'] = (time_num >= 93000) & (time_num <= 160000)
        df['isGhostPrint'] = (time_num >= 75900) & (time_num <= 81500)
        df['isOpenOrClose'] = ((time_num >= 93000) & (time_num <= 93500)) | ((time_num >= 155900) & (time_num <= 160500))
        
        df['isMinimumVolumePerCandle'] = df['Volume'] >= 200 # 20,000 shares if V is in 100s, but here Volume is actual. Wait, if V is actual, 200 might mean 20,000? Let's use 200 as in script.
        df['isMinimumVolumeAverage'] = df['TodayVolume'] >= 10000
        
        df['Ref_V_1'] = df['Volume'].shift(1)
        df['Ref_V_2'] = df['Volume'].shift(2)
        df['Ref_V_3'] = df['Volume'].shift(3)
        df['Ref_V_4'] = df['Volume'].shift(4)
        df['isRefVolumeZero'] = (df['Ref_V_1'] == 0) | (df['Ref_V_2'] == 0) | (df['Ref_V_3'] == 0) | (df['Ref_V_4'] == 0)
        
        # Market variables
        marketVolumeFactor = 2
        marketAtrFlushFactor = 2
        marketAtrSwipeFactor = 2
        
        # Note: AFL ref(ATR(3),3) we'll assume is shift(3). Actually, let's look at standard AmiBroker usage.
        # Ref(ATR(3), -3) is 3 bars ago. Ref(ATR(3), 3) is 3 bars ahead (repainted).
        # We will use shift(3) meaning 3 bars BEFORE (past), because that's what's realistic for a backtest or live trading.
        df['swipe'] = (~df['isRefVolumeZero']) & df['isMinimumVolumeAverage'] & (df['Volume'] > marketVolumeFactor * df['fastVolumeAverage']) & (df['ATR_1'] > marketAtrSwipeFactor * df['ATR_3'].shift(3)) & (df['High'] >= df['High'].shift(1)) & (df['High'] >= df['HHV_30'])
        
        df['flush'] = (~df['isRefVolumeZero']) & df['isMinimumVolumeAverage'] & (df['Volume'] > marketVolumeFactor * df['fastVolumeAverage']) & (df['ATR_1'] > marketAtrFlushFactor * df['ATR_2'].shift(5)) & (df['Low'] <= df['Low'].shift(1)) & (df['Low'] <= df['LLV_30'])
        
        df['isMarketSwipe'] = df['swipe'] & df['isMarketHours']
        df['isMarketFlush'] = df['flush'] & df['isMarketHours']
        
        # Assuming not a GLOBEX name (we don't have Name() here, typical user is trading stocks)
        preMarketVolumeFactor = 2
        preMarketAtrFactor = 1.5
        
        df['isPreMarketSwipe'] = df['isMinimumVolumeAverage'] & (df['Volume'] > preMarketVolumeFactor * df['fastVolumeAverage']) & (df['ATR_1'] > preMarketAtrFactor * df['ATR_3'].shift(3)) & (df['High'] >= df['High'].shift(1)) & (df['High'] >= df['HHV_10']) & (~df['isMarketHours']) & (~df['isGhostPrint'])
        
        df['isPreMarketFlush'] = df['isMinimumVolumeAverage'] & (df['Volume'] > preMarketVolumeFactor * df['fastVolumeAverage']) & (df['ATR_1'] > preMarketAtrFactor * df['ATR_2'].shift(5)) & (df['Low'] <= df['Low'].shift(1)) & (df['Low'] <= df['LLV_10']) & (~df['isMarketHours']) & (~df['isGhostPrint'])
        
        # final logic
        df['shouldPrintDownTriangle'] = (df['isMarketSwipe'] | df['isPreMarketSwipe']) & ~((df['isPreMarketFlush'] | df['isMarketFlush']) & (df['Close'] > df['Open']))
        df['shouldPrintUpTriangle'] = (df['isMarketFlush'] | df['isPreMarketFlush']) & ~((df['isPreMarketSwipe'] | df['isMarketSwipe']) & (df['Open'] > df['Close']))
        
        df['isHighVolTri'] = df['isHighestVolumeOfDay'] & df['isMarketHours'] & (~df['isOpenOrClose'])
        
        # Map back to a single string for simplicity on the frontend
        # Priority: Swipe/Flush over HighVol
        conditions = [
            df['shouldPrintDownTriangle'],
            df['shouldPrintUpTriangle'],
            df['isHighVolTri']
        ]
        choices = ['swipe', 'flush', 'high_vol']
        df['marker_type'] = np.select(conditions, choices, default=None)
        # convert numpy "None" or "nan" string to actual python None
        df['marker_type'] = df['marker_type'].replace('nan', None)
        
        return df
