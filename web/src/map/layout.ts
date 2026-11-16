// Hand-placed OpenTelemetry Demo topology, ported from the locked mockup.
export type ServiceId =
  | 'frontend-proxy' | 'frontend' | 'ad' | 'recommendation' | 'currency' | 'cart' | 'checkout' | 'shipping'
  | 'product-catalog' | 'valkey-cart' | 'payment' | 'email' | 'kafka' | 'quote' | 'accounting' | 'fraud-detection'

export const NODES: Record<ServiceId, [number, number]> = {
  'frontend-proxy': [40, 240], frontend: [150, 240], ad: [290, 40], recommendation: [290, 105], currency: [290, 175],
  cart: [290, 245], checkout: [290, 330], shipping: [290, 420], 'product-catalog': [440, 105], 'valkey-cart': [440, 245],
  payment: [440, 300], email: [440, 350], kafka: [440, 400], quote: [440, 455], accounting: [590, 370],
  'fraud-detection': [590, 430],
}

export const EDGES: [ServiceId, ServiceId][] = [
  ['frontend-proxy', 'frontend'], ['frontend', 'ad'], ['frontend', 'recommendation'], ['frontend', 'currency'],
  ['frontend', 'cart'], ['frontend', 'checkout'], ['frontend', 'shipping'], ['recommendation', 'product-catalog'],
  ['cart', 'valkey-cart'], ['checkout', 'cart'], ['checkout', 'payment'], ['checkout', 'email'], ['checkout', 'kafka'],
  ['shipping', 'quote'], ['kafka', 'accounting'], ['kafka', 'fraud-detection'],
]

// Where the symptom shows, with a stagger in seconds.
export const LIT: Partial<Record<ServiceId, number>> = { frontend: 0.2, 'frontend-proxy': 0.35, checkout: 0.3, payment: 0.45 }

export const PATH: ReadonlySet<string> = new Set(['frontend-proxy>frontend', 'frontend>cart', 'cart>valkey-cart'])

export const FULL_VIEWBOX = '0 0 640 480'
export const PHONE_VIEWBOX = '20 150 520 220'
export const PHONE_LABELS: ServiceId[] = ['frontend', 'cart', 'valkey-cart', 'checkout', 'payment']
