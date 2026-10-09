import { useMemo, useState } from 'react'
import {
  loadFavoritePlaces,
  removeFavoritePlace,
  setFavoriteLabel,
  toggleFavoritePlace,
} from './favoritePlaces'
import type { FavoriteLabel, FavoritePlace } from './favoritePlaces'
import type { Place } from './types'

export function useFavoritePlaces() {
  const [favorites, setFavorites] = useState<FavoritePlace[]>(loadFavoritePlaces)
  const home = useMemo(() => favorites.find((item) => item.label === 'home') ?? null, [favorites])
  const work = useMemo(() => favorites.find((item) => item.label === 'work') ?? null, [favorites])

  return {
    favorites,
    home,
    work,
    toggle: (place: Place) => setFavorites(toggleFavoritePlace(place)),
    setLabel: (place: Place, label: FavoriteLabel) => setFavorites(setFavoriteLabel(place, label)),
    remove: (id: string) => setFavorites(removeFavoritePlace(id)),
    isFavorite: (id: string) => favorites.some((item) => item.place.id === id),
  }
}
