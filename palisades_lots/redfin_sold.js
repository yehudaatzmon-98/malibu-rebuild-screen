// Run in the browser on any https://www.redfin.com page (javascript tool). Returns one line per
// house sold in 90272 in the last DAYS days, in the format update_comps.py --new expects:
// sold_date|address|price|sqft|year_built|lot_sf|lat|lon|status|mls|url
// mpt=99 is what makes the gis API return SOLD homes; without it you get active listings.
const DAYS = 45;
const u = `/stingray/api/gis?al=1&market=socal&mpt=99&num_homes=500&ord=redfin-recommended-asc&page_number=1&region_id=37583&region_type=2&sold_within_days=${DAYS}&start=0&status=9&uipt=1&v=8`;
const h = JSON.parse((await fetch(u).then(r => r.text())).replace(/^\{\}&&/, '')).payload.homes;
h.filter(x => x.soldDate && x.price?.value).map(x => [
  new Date(x.soldDate).toISOString().slice(0, 10), x.streetLine?.value, x.price?.value, x.sqFt?.value ?? '',
  x.yearBuilt?.value ?? '', x.lotSize?.value ?? '', x.latLong?.value?.latitude?.toFixed(6), x.latLong?.value?.longitude?.toFixed(6),
  x.mlsStatus || 'Sold', x.mlsId?.value || '', x.url].join('|')).join('\n');
