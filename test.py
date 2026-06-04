import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("C:/Users/liewmh/Desktop/REPORT/MELEC-02-EMSB-D1/PQA_Extracted Data/MELEC-02-UMSB-MCC-D1.csv")
df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], dayfirst=True)

# Use absolute value for magnitude plot
df['PF1_plot'] = df['PF1_AVG'].abs()
df['PF2_plot'] = df['PF2_AVG'].abs()
df['PF3_plot'] = df['PF3_AVG'].abs()

fig, ax = plt.subplots(figsize=(14, 5))
ax.plot(df['Datetime'], df['PF1_plot'], label='PF L1')
ax.plot(df['Datetime'], df['PF2_plot'], label='PF L2')
ax.plot(df['Datetime'], df['PF3_plot'], label='PF L3')
ax.set_ylim(0, 1.05)
ax.set_ylabel('Power Factor')
ax.set_title('Power Factor Trend - MELEC-02-UMSB-NC-D1')
ax.legend()
plt.tight_layout()
plt.show()