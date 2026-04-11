import pandas as pd
df = pd.read_csv("sleep_data.csv")
print(df.columns.tolist())
print(df.head())