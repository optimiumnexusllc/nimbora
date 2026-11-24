'use client';

import { createContext, ReactNode, useContext } from 'react';

import { Brand, DEFAULT_BRAND } from '@/lib/brand';

/** The platform's charter, read on the server by the root layout (lib/brand.ts). */
const BrandContext = createContext<Brand>(DEFAULT_BRAND);

export function BrandProvider({ brand, children }: { brand: Brand; children: ReactNode }) {
    return <BrandContext.Provider value={brand}>{children}</BrandContext.Provider>;
}

export function useBrand(): Brand {
    return useContext(BrandContext);
}
