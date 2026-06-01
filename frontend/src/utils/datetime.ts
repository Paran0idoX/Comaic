const localeName = (locale: string) => (locale === 'zh' ? 'zh-CN' : 'en-US')

export const formatLocalDateTime = (
  value: string | null | undefined,
  locale: string,
  options?: Intl.DateTimeFormatOptions,
) => {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return new Intl.DateTimeFormat(
    localeName(locale),
    options ?? {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    },
  ).format(date)
}

export const formatLocalNowTime = (locale: string) =>
  new Intl.DateTimeFormat(localeName(locale), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date())
