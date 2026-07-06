package com.analogintuition.intune

import android.app.Application

class IntuneApplication : Application() {

    lateinit var bleClient: BleStreamClient
        private set

    override fun onCreate() {
        super.onCreate()
        bleClient = BleStreamClient(applicationContext)
    }
}