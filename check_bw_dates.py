import pandas as pd

df = pd.read_csv('data/bw_34gap.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

print(f"\nDate range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print(f"Total bars: {len(df)}")

print(f"\nBars per day:")
df['date'] = df['timestamp'].dt.date
print(df.groupby('date').size())

print(f"\nFirst 10 bars:")
print(df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].head(10))

print(f"\nLast 10 bars:")
print(df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].tail(10))