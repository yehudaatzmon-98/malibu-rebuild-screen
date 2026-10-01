// Run in the browser on any https://www.redfin.com page (javascript tool). Returns every ACTIVE land
// listing in 90272, one per line, in the format update_lots.py --land expects:
// address|price|lot_sf|lat|lon|redfin_property_id
const u = "/stingray/api/gis?al=1&market=socal&num_homes=500&region_id=37583&region_type=2&status=9&uipt=5&v=8";
const h = JSON.parse((await fetch(u).then(r => r.text())).replace(/^\{\}&&/, '')).payload.homes.filter(x => x.uiPropertyType == 5);
h.map(x => [x.streetLine?.value, x.price?.value, x.lotSize?.value ?? '', (+x.latLong?.value?.latitude).toFixed(5),
  (+x.latLong?.value?.longitude).toFixed(5), x.propertyId].join('|')).join('\n');
