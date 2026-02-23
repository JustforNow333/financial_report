const NUMBER_FORMATTER = new Intl.NumberFormat("en-US");
const ET_TIMESTAMP_FORMATTER = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: true,
  timeZone: "America/New_York",
});

export const formatMoney = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `$${value.toFixed(2)}`;
};

export const formatPct = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};

export const formatVolume = (value: number | null): string => {
  if (value === null) {
    return "-";
  }
  return NUMBER_FORMATTER.format(value);
};

export const formatEtTimestamp = (iso: string): string => {
  const date = new Date(iso);
  return ET_TIMESTAMP_FORMATTER.format(date);
};
