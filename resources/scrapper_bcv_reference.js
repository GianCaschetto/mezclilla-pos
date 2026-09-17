import axios from 'axios';
import * as cheerio from 'cheerio';
import { Router } from 'express';
import https from 'https';

const router = Router();
const url = 'https://www.bcv.org.ve/';

// Cache en memoria para las tasas del BCV
let bcvCache = {
    data: null,
    lastUpdate: null,
    isUpdating: false
};

// TTL del cache: 5 minutos (300,000 ms)
const CACHE_TTL = 5 * 60 * 1000;

// Función para verificar si el cache es válido
function isCacheValid() {
    if (!bcvCache.data || !bcvCache.lastUpdate) {
        return false;
    }
    
    const now = Date.now();
    const cacheAge = now - bcvCache.lastUpdate;
    
    return cacheAge < CACHE_TTL;
}

// Función para obtener tasas del BCV (con cache)
async function getBCVRates() {
    try {
        // Si el cache es válido, retornar datos del cache
        if (isCacheValid()) {
            return {
                success: true,
                ...bcvCache.data,
                fromCache: true,
                cacheAge: Date.now() - bcvCache.lastUpdate
            };
        }
        
        // Si ya se está actualizando, esperar
        if (bcvCache.isUpdating) {
            console.log('⏳ Cache se está actualizando, esperando...');
            // Esperar hasta 10 segundos por la actualización
            let attempts = 0;
            while (bcvCache.isUpdating && attempts < 20) {
                await new Promise(resolve => setTimeout(resolve, 500));
                attempts++;
            }
            
            // Si después de esperar el cache es válido, retornarlo
            if (isCacheValid()) {
                return {
                    success: true,
                    ...bcvCache.data,
                    fromCache: true,
                    cacheAge: Date.now() - bcvCache.lastUpdate
                };
            }
        }
        
        // Marcar que se está actualizando
        bcvCache.isUpdating = true;
        
        console.log('🔄 Actualizando cache del BCV...');
        
        const response = await axios.get(url, {
            httpsAgent: new https.Agent({
                rejectUnauthorized: false,
            }),
            timeout: 10000, // 10 segundos de timeout
        });
        
        if (response && response.data) {
            const $ = cheerio.load(response.data);
            const dollar = $('#dolar strong').text();
            const euro = $('#euro strong').text();
        
            const dollarRate = Number(dollar.replace(',', '.'));
            const euroRate = Number(euro.replace(',', '.'));
            
            // Validar que las tasas sean números válidos
            if (isNaN(dollarRate) || isNaN(euroRate)) {
                throw new Error('Tasas inválidas obtenidas del BCV');
            }
            
            // Actualizar cache
            bcvCache.data = {
                dollar: dollarRate,
                euro: euroRate,
                date: new Date().toISOString()
            };
            bcvCache.lastUpdate = Date.now();
            
            console.log('✅ Cache del BCV actualizado exitosamente');
            
            return {
                success: true,
                dollar: dollarRate,
                euro: euroRate,
                date: new Date().toISOString(),
                fromCache: false,
                cacheAge: 0
            };
            
        } else {
            throw new Error('La respuesta de Axios es nula o no tiene datos');
        }
        
    } catch (error) {
        console.error('❌ Error obteniendo tasas del BCV:', error.message);
        
        // Si hay error pero tenemos cache válido, retornar cache
        if (isCacheValid()) {
            console.log('⚠️ Retornando cache anterior debido al error');
            return {
                success: true,
                ...bcvCache.data,
                fromCache: true,
                cacheAge: Date.now() - bcvCache.lastUpdate,
                warning: 'Datos del cache debido a error en actualización'
            };
        }
        
        throw error;
        
    } finally {
        // Siempre marcar que ya no se está actualizando
        bcvCache.isUpdating = false;
    }
}

// Endpoint principal para obtener tasas del BCV
router.get('/bcv', async (req, res) => {
    try {
        const rates = await getBCVRates();
        res.json(rates);
        
    } catch (error) {
        console.error('❌ Error en endpoint /bcv:', error.message);
        res.status(500).json({ 
            success: false, 
            message: error.message,
            error: 'Error obteniendo tasas del BCV'
        });
    }
});

// Endpoint para forzar actualización del cache
router.post('/bcv/refresh', async (req, res) => {
    try {
        // Invalidar cache forzando actualización
        bcvCache.lastUpdate = 0;
        
        console.log('🔄 Forzando actualización del cache...');
        const rates = await getBCVRates();
        
        res.json({
            success: true,
            message: 'Cache actualizado forzadamente',
            ...rates
        });
        
    } catch (error) {
        console.error('❌ Error forzando actualización:', error.message);
        res.status(500).json({ 
            success: false, 
            message: error.message,
            error: 'Error forzando actualización del cache'
        });
    }
});

// Endpoint para ver estado del cache
router.get('/bcv/status', (req, res) => {
    const now = Date.now();
    const cacheAge = bcvCache.lastUpdate ? now - bcvCache.lastUpdate : null;
    const isValid = isCacheValid();
    
    res.json({
        success: true,
        cache: {
            hasData: !!bcvCache.data,
            lastUpdate: bcvCache.lastUpdate,
            cacheAge: cacheAge,
            isValid: isValid,
            isUpdating: bcvCache.isUpdating,
            ttl: CACHE_TTL,
            ttlRemaining: isValid ? CACHE_TTL - cacheAge : 0
        },
        data: bcvCache.data,
        timestamp: new Date().toISOString()
    });
});

// Endpoint para limpiar cache
router.delete('/bcv/cache', (req, res) => {
    bcvCache = {
        data: null,
        lastUpdate: null,
        isUpdating: false
    };
    
    console.log('🧹 Cache del BCV limpiado');
    
    res.json({
        success: true,
        message: 'Cache limpiado exitosamente',
        timestamp: new Date().toISOString()
    });
});

export default router;
