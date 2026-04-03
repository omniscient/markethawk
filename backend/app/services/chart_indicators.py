import pandas as pd
import numpy as np

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
        
        # Calculate daily volume / cumulative volume
        df['TodayVolume'] = df.groupby(date_col)['Volume'].cumsum()
        
        # VWAP calculation starting from 04:00:00 per day
        # In Pandas, doing cumsum by day handles the start automatically.
        # But wait, VWAP might technically only calculate when Time >= 04:00:00
        # If there's early data, we filter. Usually Polygon extended hours start at 04:00:00.
        df['cum_C_V'] = (df['Close'] * df['Volume']).groupby(date_col).cumsum()
        df['vwap_intraday'] = df['cum_C_V'] / df['TodayVolume']
        
        df['Vol_MA_5'] = df['Volume'].rolling(5).mean()
        # AFL Ref(MA(V, 5), 5) - we use backward shift (past bar lookback) for non-repainting logic
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
        # TimeNum() in AFL = HHMMSS as an integer (e.g. 9:30:00 -> 93000)
        # We replicate this with: hour*10000 + minute*100 + second
        hour = df.index.hour
        minute = df.index.minute
        second = df.index.second
        time_num = hour * 10000 + minute * 100 + second
        
        df['isMarketHours'] = (time_num >= 93000) & (time_num <= 160000)
        df['isGhostPrint'] = (time_num >= 75900) & (time_num <= 81500)
        df['isOpenOrClose'] = ((time_num >= 93000) & (time_num <= 93500)) | ((time_num >= 155900) & (time_num <= 160500))
        
        # Market hour conditions
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
        
        # AFL Ref(ATR(N), N) - implemented as past lookback shift(N) for non-repainting behaviour
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
        # np.select with default=None returns the string '0' or 'None' in some numpy versions.
        # Use default='' and then convert to None for clean JSON serialization.
        result = np.select(conditions, choices, default='')
        df['marker_type'] = pd.array(result, dtype=object)
        df['marker_type'] = df['marker_type'].where(df['marker_type'] != '', other=None)
        
        # Drop intermediate calculation columns to keep payload slim
        cols_to_drop = [
            'cum_C_V', 'TodayVolume', 'Vol_MA_5', 'fastVolumeAverage',
            'ATR_1', 'ATR_2', 'ATR_3', 'ATR_10',
            'HHV_30', 'LLV_30', 'HHV_10', 'LLV_10',
            'HHV_Vol_Today', 'isHighestVolumeOfDay',
            'isMarketHours', 'isGhostPrint', 'isOpenOrClose',
            'isMinimumVolumePerCandle', 'isMinimumVolumeAverage',
            'Ref_V_1', 'Ref_V_2', 'Ref_V_3', 'Ref_V_4', 'isRefVolumeZero',
            'swipe', 'flush', 'isMarketSwipe', 'isMarketFlush',
            'isPreMarketSwipe', 'isPreMarketFlush',
            'shouldPrintDownTriangle', 'shouldPrintUpTriangle', 'isHighVolTri',
        ]
        df = df.drop(columns=[c for c in cols_to_drop if c in df.columns])
        # Convert back to UTC for standard serialization
        df.index = df.index.tz_convert('UTC')
        
        return df
