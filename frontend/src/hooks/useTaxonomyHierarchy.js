import { useMemo } from 'react'

/**
 * Build the d3-hierarchy input from documents + taxonomy domain map.
 *
 * Output shape:
 * {
 *   name: 'corpus',
 *   children: [
 *     {
 *       name: 'legal-compliance', count: 2,
 *       children: [
 *         {
 *           name: 'regulation-policy', count: 2,
 *           children: [
 *             { name: 'regulatory-guidance', count: 2 }
 *           ]
 *         }
 *       ]
 *     }
 *   ]
 * }
 *
 * Docs with NULL primary_category are skipped (the sidebar's
 * "Uncategorized" entry handles them separately).
 *
 * Subtags are placed under their owning *domain* by looking up
 * `domainOptions[primary]`. A subtag that is itself a domain (i.e.
 * appears as a key in domainOptions[primary]) becomes the domain node
 * directly; deeper sub-domain values nest inside.
 */
export function useTaxonomyHierarchy(documents, taxonomyData) {
  return useMemo(() => {
    const tree = { name: 'corpus', children: [] }
    if (!Array.isArray(documents) || documents.length === 0) {
      return tree
    }
    const domainOptions = taxonomyData?.domain_options || {}

    /** category -> domain -> subdomain -> count */
    const counts = new Map()

    for (const doc of documents) {
      const primary = doc.primary_category
      if (!primary) continue

      const domainsOfPrimary = domainOptions[primary] || []
      const domainSet = new Set(domainsOfPrimary)

      // Bucket sub-tags into (domain, sub-domain) pairs based on whether
      // the tag itself is a domain or a sub-domain of this primary.
      const subtags = Array.isArray(doc.subtags) ? doc.subtags : []
      const buckets = []
      const seenDomains = new Set()

      // First pass: subtags that ARE domain names (depth-2 hits)
      for (const tag of subtags) {
        if (domainSet.has(tag)) {
          buckets.push({ domain: tag, sub: null })
          seenDomains.add(tag)
        }
      }
      // Second pass: subtags that are sub-domain values — find their parent domain
      // (We don't have the explicit subdomain → domain map; we use a heuristic:
      // a tag not in domainSet falls under a "general" domain bucket of the primary,
      // OR under the first domain seen for this doc if any.)
      const fallbackDomain = buckets[0]?.domain || (domainsOfPrimary[0] || primary)
      for (const tag of subtags) {
        if (!domainSet.has(tag)) {
          buckets.push({ domain: fallbackDomain, sub: tag })
        }
      }
      // If the doc has primary but no usable subtags, count it under the primary directly
      if (buckets.length === 0) {
        buckets.push({ domain: null, sub: null })
      }

      const catMap = counts.get(primary) || new Map()
      for (const b of buckets) {
        const domKey = b.domain || '__direct__'
        const subMap = catMap.get(domKey) || new Map()
        const subKey = b.sub || '__direct__'
        subMap.set(subKey, (subMap.get(subKey) || 0) + 1)
        catMap.set(domKey, subMap)
      }
      counts.set(primary, catMap)
    }

    // Convert nested Maps → tree
    for (const [primary, catMap] of counts.entries()) {
      const catChildren = []
      let catTotal = 0

      for (const [domain, subMap] of catMap.entries()) {
        let domTotal = 0
        const domChildren = []

        for (const [sub, n] of subMap.entries()) {
          domTotal += n
          if (sub !== '__direct__') {
            domChildren.push({ name: sub, count: n })
          }
        }

        if (domain === '__direct__') {
          // Doc had primary but no domain-level subtag at all
          catTotal += domTotal
          // Don't push a domain-level node — count flows up to the primary
          continue
        }

        catTotal += domTotal
        catChildren.push({
          name: domain,
          count: domTotal,
          ...(domChildren.length > 0 ? { children: domChildren } : {}),
        })
      }

      tree.children.push({
        name: primary,
        count: catTotal,
        ...(catChildren.length > 0 ? { children: catChildren } : {}),
      })
    }

    // Stable sort: primary by count desc; nested by count desc
    const sortByCount = (a, b) => (b.count || 0) - (a.count || 0)
    tree.children.sort(sortByCount)
    tree.children.forEach(c => {
      if (c.children) c.children.sort(sortByCount)
      if (c.children) c.children.forEach(d => {
        if (d.children) d.children.sort(sortByCount)
      })
    })

    return tree
  }, [documents, taxonomyData])
}
